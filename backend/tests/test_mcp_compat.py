"""MCP SDK generation compat: streamable-HTTP resolution + tool permissions.

The `mcp` package renamed `streamablehttp_client` (1.x) to
`streamable_http_client` with a different signature (2.x). These tests stub
both module shapes and verify our branching — they run with or without the
real SDK installed.
"""

from __future__ import annotations

import sys
import types

import pytest


def _install_stub(gen: str, monkeypatch) -> None:
    """Install a fake `mcp.client.streamable_http` of generation v1 or v2."""
    pkg = types.ModuleType("mcp")
    pkg.__path__ = []  # mark as package
    client = types.ModuleType("mcp.client")
    client.__path__ = []
    mod = types.ModuleType("mcp.client.streamable_http")

    if gen == "v2":
        async def streamable_http_client(*args, **kwargs):  # noqa: F811
            raise AssertionError("stub client must not run")

        mod.streamable_http_client = streamable_http_client
    elif gen == "v1":
        async def streamablehttp_client(*args, **kwargs):  # noqa: F811
            raise AssertionError("stub client must not run")

        mod.streamablehttp_client = streamablehttp_client
    else:
        raise ValueError(gen)

    monkeypatch.setitem(sys.modules, "mcp", pkg)
    monkeypatch.setitem(sys.modules, "mcp.client", client)
    monkeypatch.setitem(sys.modules, "mcp.client.streamable_http", mod)


def test_resolve_v2_shape(monkeypatch):
    _install_stub("v2", monkeypatch)
    from app.mcp import manager as mcp_manager

    kind, factory = mcp_manager.resolve_streamable_factory()
    assert kind == "v2"
    assert factory.__name__ == "streamable_http_client"


def test_resolve_v1_shape(monkeypatch):
    _install_stub("v1", monkeypatch)
    from app.mcp import manager as mcp_manager

    kind, factory = mcp_manager.resolve_streamable_factory()
    assert kind == "v1"
    assert factory.__name__ == "streamablehttp_client"


def test_resolve_missing_sdk_raises(monkeypatch):
    monkeypatch.delitem(sys.modules, "mcp", raising=False)
    monkeypatch.delitem(sys.modules, "mcp.client", raising=False)
    monkeypatch.delitem(sys.modules, "mcp.client.streamable_http", raising=False)
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "mcp.client.streamable_http" or name.startswith("mcp.client.streamable_http."):
            raise ImportError("No module named 'mcp'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    from app.mcp import manager as mcp_manager

    with pytest.raises(ImportError):
        mcp_manager.resolve_streamable_factory()


def test_mcp_tools_stay_approval_gated():
    """Third-party MCP server tools must never auto-run: even read-only
    names stay write/mutating so ask mode always prompts."""
    from app.mcp import manager as mcp_manager
    from app.tools.registry import registry

    class FakeConn:
        name = "evil"

    conn = FakeConn()
    conn.state = mcp_manager.MCPServerState(
        name="evil",
        transport="stdio",
        status="running",
        tools=[
            mcp_manager.MCPToolInfo(
                server="evil", name="get_secrets", qualified="mcp__evil__get_secrets",
                description="totally innocent",
            )
        ],
    )
    registered = {}
    real_register = registry.register
    registry.register = lambda tool: registered.__setitem__(tool.name, tool)
    try:
        mcp_manager.mcp_manager._register_tools(conn)
    finally:
        registry.register = real_register
    tool = registered["mcp__evil__get_secrets"]
    assert tool.permission == "write"
    assert tool.mutating is True
