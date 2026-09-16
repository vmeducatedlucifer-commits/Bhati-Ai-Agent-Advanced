"""MCP client manager.

Each server runs in its own supervisor task that owns the connection's async context
for its whole lifetime; callers talk to it through a request queue. That avoids the
cross-task cancellation problems you hit when an AsyncExitStack is entered in one task
and exited in another.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger

log = get_logger("app.mcp")


@dataclass(slots=True)
class MCPToolInfo:
    server: str
    name: str            # original tool name on the server
    qualified: str       # mcp__<server>__<name>
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MCPServerState:
    name: str
    transport: str
    status: str = "starting"   # starting | running | error | stopped
    error: str = ""
    tools: list[MCPToolInfo] = field(default_factory=list)


def resolve_streamable_factory() -> tuple[str, Any]:
    """Streamable-HTTP client across SDK generations.

    SDK 1.x exposes `streamablehttp_client(url, headers=...)` yielding
    (read, write, session_id); SDK 2.x renamed it to `streamable_http_client`
    with `(url, *, http_client=...)` yielding (read, write) and headers baked
    into the HTTP client. Returns ("v1"|"v2", factory).
    """
    try:
        from mcp.client.streamable_http import streamable_http_client

        return "v2", streamable_http_client
    except ImportError:
        from mcp.client.streamable_http import streamablehttp_client

        return "v1", streamablehttp_client


def make_v2_http_client(headers: dict[str, str] | None):
    """HTTP client carrying auth headers for SDK 2.x (best-effort chain)."""
    if headers:
        try:
            from mcp.shared._httpx_utils import create_mcp_http_client

            return create_mcp_http_client(headers=headers)
        except ImportError:
            pass
        try:
            import httpx2

            return httpx2.AsyncClient(headers=headers)
        except ImportError:
            pass
        log.warning("could not attach MCP auth headers: no compatible HTTP client")
    return None


class _Connection:
    """Supervisor for one MCP server."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.name: str = config["name"]
        self.state = MCPServerState(name=self.name, transport=config.get("transport", "stdio"))
        self._requests: asyncio.Queue[tuple[str, dict[str, Any], asyncio.Future]] = asyncio.Queue()
        self._ready = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self, timeout: float = 60.0) -> MCPServerState:
        self._task = asyncio.create_task(self._run(), name=f"mcp:{self.name}")
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=timeout)
        except TimeoutError:
            self.state.status = "error"
            self.state.error = f"server did not become ready within {timeout:.0f}s"
        return self.state

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        self.state.status = "stopped"

    async def call(self, tool: str, arguments: dict[str, Any], timeout: float = 300.0) -> str:
        if self.state.status != "running":
            raise RuntimeError(f"MCP server '{self.name}' is {self.state.status}: {self.state.error}")
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        await self._requests.put((tool, arguments, future))
        return await asyncio.wait_for(future, timeout=timeout)

    # ---- supervisor ------------------------------------------------------

    async def _run(self) -> None:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as exc:
            self.state.status = "error"
            self.state.error = f"mcp package not installed: {exc}"
            self._ready.set()
            return

        transport = self.config.get("transport", "stdio")
        try:
            if transport == "stdio":
                from app.core.env import sandbox_env

                params = StdioServerParameters(
                    command=self.config["command"],
                    args=list(self.config.get("args") or []),
                    # Never inherit the full host env: one printenv in a
                    # third-party server would exfiltrate every secret.
                    env={**sandbox_env(), **(self.config.get("env") or {})},
                )
                async with stdio_client(params) as (read, write):
                    await self._serve(ClientSession, read, write)
            elif transport == "sse":
                from mcp.client.sse import sse_client

                async with sse_client(
                    self.config["url"], headers=self.config.get("headers") or {}
                ) as (read, write):
                    await self._serve(ClientSession, read, write)
            elif transport in ("http", "streamable_http"):
                kind, factory = resolve_streamable_factory()
                headers = self.config.get("headers") or {}
                if kind == "v2":
                    http_client = make_v2_http_client(headers)
                    kwargs: dict[str, Any] = {}
                    if http_client is not None:
                        kwargs["http_client"] = http_client
                    async with factory(self.config["url"], **kwargs) as (read, write):
                        await self._serve(ClientSession, read, write)
                else:
                    async with factory(
                        self.config["url"], headers=headers
                    ) as (read, write, _):
                        await self._serve(ClientSession, read, write)
            else:
                raise ValueError(f"unsupported transport: {transport}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("mcp server %s failed: %s", self.name, exc)
            self.state.status = "error"
            self.state.error = str(exc)
        finally:
            self._ready.set()

    async def _serve(self, ClientSession, read, write) -> None:
        async with ClientSession(read, write) as session:
            await session.initialize()
            listing = await session.list_tools()
            self.state.tools = [
                MCPToolInfo(
                    server=self.name,
                    name=t.name,
                    qualified=f"mcp__{self.name}__{t.name}",
                    description=t.description or f"{self.name} tool {t.name}",
                    input_schema=getattr(t, "inputSchema", None)
                    or getattr(t, "input_schema", None)
                    or {"type": "object", "properties": {}},
                )
                for t in listing.tools
            ]
            self.state.status = "running"
            self.state.error = ""
            self._ready.set()
            log.info("mcp server %s ready with %d tool(s)", self.name, len(self.state.tools))

            while True:
                tool, arguments, future = await self._requests.get()
                try:
                    result = await session.call_tool(tool, arguments)
                    parts: list[str] = []
                    for block in result.content or []:
                        text = getattr(block, "text", None)
                        parts.append(text if text is not None else str(block))
                    payload = "\n".join(parts) or "(no output)"
                    if getattr(result, "isError", False):
                        payload = f"ERROR: {payload}"
                    if not future.done():
                        future.set_result(payload)
                except Exception as exc:
                    if not future.done():
                        future.set_exception(exc)


class MCPManager:
    def __init__(self) -> None:
        self._connections: dict[str, _Connection] = {}

    async def start(self, config: dict[str, Any]) -> MCPServerState:
        conn = await self.prepare(config)
        return await self.finish(conn)

    async def prepare(self, config: dict[str, Any]) -> _Connection:
        """Register the supervisor immediately (status "starting") so API
        responses and the UI never show a stale state while the server boots."""
        name = config["name"]
        await self.stop(name)
        conn = _Connection(config)
        self._connections[name] = conn
        return conn

    async def finish(self, conn: _Connection) -> MCPServerState:
        """Wait for readiness (up to 60s) and register tools. Awaits the
        supervisor — run it in a background task to keep HTTP fast."""
        state = await conn.start()
        if state.status == "running":
            self._register_tools(conn)
        return state

    async def stop(self, name: str) -> None:
        conn = self._connections.pop(name, None)
        if conn:
            await conn.stop()
        from app.tools.registry import registry

        registry.unregister_prefix(f"mcp__{name}__")

    async def stop_all(self) -> None:
        for name in list(self._connections):
            await self.stop(name)

    def state(self, name: str) -> MCPServerState | None:
        conn = self._connections.get(name)
        return conn.state if conn else None

    def states(self) -> list[MCPServerState]:
        return [c.state for c in self._connections.values()]

    def tools(self) -> list[MCPToolInfo]:
        return [t for c in self._connections.values() for t in c.state.tools]

    async def call(self, qualified: str, arguments: dict[str, Any]) -> str:
        _, server, tool = qualified.split("__", 2)
        conn = self._connections.get(server)
        if not conn:
            raise RuntimeError(f"MCP server '{server}' is not running")
        return await conn.call(tool, arguments)

    # ---- registry wiring -------------------------------------------------

    def _register_tools(self, conn: _Connection) -> None:
        from app.tools.base import Tool
        from app.tools.registry import registry

        # MCP servers are third-party code the user installed: their tools
        # stay approval-gated ("write") even when read-only named, so a
        # malicious server can never auto-run actions in ask mode.
        for info in conn.state.tools:
            registry.register(
                Tool(
                    name=info.qualified,
                    description=f"[{conn.name}] {info.description}",
                    parameters=info.input_schema or {"type": "object", "properties": {}},
                    handler=self._make_handler(info.qualified),
                    permission="write",
                    group=f"mcp:{conn.name}",
                    mutating=True,
                )
            )

    def _make_handler(self, qualified: str):
        from app.tools.base import ToolResult

        async def handler(ctx, **kwargs):
            try:
                output = await self.call(qualified, kwargs)
            except Exception as exc:
                return ToolResult.error(f"{qualified} failed: {exc}")
            return ToolResult(content=output, display={"kind": "text", "text": output})

        return handler


mcp_manager = MCPManager()
