"""Live preview: run a dev server in the sandbox and show it to the user in-app.

The backend proxies `/api/v1/preview/{thread}/{port}/…` to the sandbox, so a Vite or
Flask server started by the agent is visible in the Browser tab without exposing ports.
"""

from __future__ import annotations

import asyncio

from app.tools.base import ToolContext, ToolResult, integer, obj, string
from app.tools.registry import registry


@registry.tool(
    "start_server",
    (
        "Start a long-running dev/preview server inside the sandbox in the background and "
        "show it in the user's Browser tab. Use for `npm run dev`, `python -m http.server`, "
        "`uvicorn`, etc. Always bind to 0.0.0.0."
    ),
    obj(
        {
            "command": string("Command that starts the server, bound to 0.0.0.0"),
            "port": integer("Port the server listens on"),
            "cwd": string("Working directory relative to the workspace", default=""),
            "wait_seconds": integer("How long to wait for it to come up", default=12),
        },
        ["command", "port"],
    ),
    permission="dangerous",
    group="preview",
    mutating=True,
)
async def start_server(ctx: ToolContext, command: str, port: int, cwd: str = "", wait_seconds: int = 12):
    log_path = f"/tmp/server-{port}.log"
    launch = f"nohup {command} > {log_path} 2>&1 & echo $!"
    res = await ctx.sandbox.exec(launch, cwd=cwd or None, timeout=30)
    if res.exit_code != 0:
        return ToolResult.error(res.combined())
    pid = res.stdout.strip().splitlines()[-1] if res.stdout.strip() else "?"

    up = False
    for _ in range(max(1, wait_seconds)):
        await asyncio.sleep(1)
        probe = await ctx.sandbox.exec(
            f"(command -v curl >/dev/null && curl -sf -o /dev/null http://127.0.0.1:{port} && echo up) || true",
            timeout=10,
        )
        if "up" in probe.stdout:
            up = True
            break

    logs = await ctx.sandbox.exec(f"tail -n 30 {log_path} 2>/dev/null || true", timeout=15)
    preview_url = f"/api/v1/preview/{ctx.thread_id}/{port}/"
    await ctx.emit("preview", {"port": port, "url": preview_url, "up": up, "command": command})

    status = "responding" if up else f"started but not responding yet after {wait_seconds}s"
    return ToolResult(
        content=(
            f"Server (pid {pid}) on port {port} — {status}.\n"
            f"Visible to the user in the Browser tab.\n"
            f"Recent log:\n{logs.stdout.strip()[:3000]}"
        ),
        display={"kind": "preview", "port": port, "url": preview_url, "up": up},
    )


@registry.tool(
    "stop_server",
    "Stop a background server previously started on a port.",
    obj({"port": integer("Port to free")}, ["port"]),
    permission="write",
    group="preview",
    mutating=True,
)
async def stop_server(ctx: ToolContext, port: int):
    await ctx.sandbox.exec(
        f"(command -v fuser >/dev/null && fuser -k {port}/tcp) || "
        f"(pkill -f ':{port}' || true)",
        timeout=30,
    )
    await ctx.emit("preview_stopped", {"port": port})
    return ToolResult(content=f"Stopped whatever was listening on port {port}.")


import re  # noqa: E402


def _normalize_preview_url(thread_id: str, url: str) -> str:
    """Rewrite any raw localhost/127.0.0.1 links to the backend's reverse proxy."""
    match = re.match(r"^https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0):(\d+)(/?.*)$", url.strip())
    if match:
        port, path = match.group(1), match.group(2).lstrip("/")
        return f"/api/v1/preview/{thread_id}/{port}/{path}"
    return url


@registry.tool(
    "open_in_browser",
    "Point the user's Browser tab at a URL (a preview server, a docs page, a deployed site).",
    obj({"url": string("Absolute URL or preview path"), "title": string("Tab label", default="")}, ["url"]),
    group="preview",
)
async def open_in_browser(ctx: ToolContext, url: str, title: str = ""):
    resolved_url = _normalize_preview_url(ctx.thread_id, url)
    await ctx.emit("browser_navigate", {"url": resolved_url, "title": title})
    return ToolResult(
        content=f"Opened {resolved_url} in the user's Browser tab.",
        display={"kind": "browser", "url": resolved_url, "title": title},
    )
