"""Connectors (GitHub, Vercel, Render, Hugging Face) and MCP servers."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import DB, Auth
from app.connectors import SERVICES, available_services, get_client
from app.core.crypto import decrypt, encrypt, mask
from app.core.errors import AppError, NotFound
from app.core.logging import get_logger
from app.core.utils import iso
from app.db.models import Connector, MCPServer
from app.mcp import mcp_manager

log = get_logger("app.integrations")

router = APIRouter(tags=["integrations"])


# ---------------------------------------------------------------------------
# Connectors
# ---------------------------------------------------------------------------


class ConnectBody(BaseModel):
    service: str
    token: str = Field(min_length=1)
    extra: dict[str, str] = Field(default_factory=dict)


@router.get("/connectors")
async def list_connectors(db: DB, _: Auth):
    rows = (await db.execute(select(Connector))).scalars().all()
    by_service = {r.service: r for r in rows}
    return [
        {
            **service,
            "connected": service["service"] in by_service,
            "account": _public_account(by_service[service["service"]].account)
            if service["service"] in by_service
            else {},
            "token_masked": mask(decrypt(by_service[service["service"]].token_enc))
            if service["service"] in by_service
            else "",
            "updated_at": iso(by_service[service["service"]].updated_at)
            if service["service"] in by_service
            else None,
        }
        for service in available_services()
    ]


def _public_account(account: Any) -> dict[str, Any]:
    """Account summary safe for API responses — never the encrypted vault."""
    if not isinstance(account, dict):
        return {}
    return {k: v for k, v in account.items() if k != "_vault"}


_MASKED = {"***", "****", "********"}


def _merge_secret_dict(old: dict[str, str], incoming: dict[str, str] | None) -> dict[str, str]:
    """Merge UI-round-tripped secrets: "***" keeps the old value, "" deletes."""
    if incoming is None:
        return old
    merged = dict(old)
    for k, v in incoming.items():
        if v in _MASKED:
            continue
        if v == "" or v is None:
            merged.pop(k, None)
        else:
            merged[k] = v
    return merged


@router.post("/connectors")
async def connect(body: ConnectBody, db: DB, _: Auth):
    meta = SERVICES.get(body.service)
    if not meta:
        raise AppError(f"Unknown service: {body.service}")

    # Keep only declared non-secret extras; the primary secret stays encrypted.
    declared = {f["key"]: f for f in meta.get("fields", [])}
    extra = {k: v for k, v in (body.extra or {}).items() if k in declared and not declared[k].get("secret")}
    build = meta.get("build") or (lambda token, extra: meta["client"](token))
    client = build(body.token, extra)
    try:
        account = await client.whoami()
    except Exception as exc:
        raise AppError(f"Token rejected by {meta['label']}: {exc}", code="bad_token") from exc
    if not isinstance(account, dict):
        account = {"result": account}
    account["_config"] = extra

    row = (
        await db.execute(select(Connector).where(Connector.service == body.service))
    ).scalar_one_or_none()
    if row:
        row.token_enc = encrypt(body.token)
        row.account = account
        row.enabled = True
    else:
        db.add(Connector(service=body.service, token_enc=encrypt(body.token), account=account))
    await db.commit()
    return {"service": body.service, "connected": True, "account": _public_account(account)}


@router.delete("/connectors/{service}")
async def disconnect(service: str, db: DB, _: Auth):
    row = (
        await db.execute(select(Connector).where(Connector.service == service))
    ).scalar_one_or_none()
    if row:
        await db.delete(row)
        await db.commit()
    return {"service": service, "connected": False}


@router.get("/connectors/{service}/probe")
async def probe(service: str, db: DB, _: Auth):
    client = await get_client(db, service)
    if not client:
        raise NotFound(f"{service} is not connected")
    try:
        return {"ok": True, "account": await client.whoami()}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# OAuth2 app flow (authorize in provider popup → callback stores tokens)
# ---------------------------------------------------------------------------


class OAuthUrlIn(BaseModel):
    client_id: str = Field(min_length=1, max_length=200)
    client_secret: str = Field(default="", max_length=500)
    redirect_uri: str = Field(min_length=8, max_length=1000)
    scopes: list[str] = Field(default_factory=list)


@router.post("/connectors/{service}/oauth/url")
async def oauth_url(service: str, body: OAuthUrlIn, _: Auth):
    """Build the provider authorize URL. Secrets stay server-side; the
    browser only ever sees the one-time state id."""
    from app.connectors import build_authorize_url

    url, state = build_authorize_url(
        service,
        client_id=body.client_id,
        client_secret=body.client_secret,
        redirect_uri=body.redirect_uri,
        scopes=body.scopes or None,
    )
    return {"url": url, "state": state}


def _oauth_page(*, ok: bool, service: str, message: str) -> HTMLResponse:
    import html as html_lib

    # Everything interpolated here can carry provider-controlled text —
    # escape it and neutralize </script> inside the JSON payload.
    safe_service = html_lib.escape(service[:60])
    safe_message = html_lib.escape(message[:300])
    payload = json.dumps(
        {"type": "bhati:oauth:done", "service": service, "ok": ok, "error": message if not ok else ""}
    ).replace("<", "\\u003c")
    return HTMLResponse(
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{'Connected' if ok else 'Failed'} — Rawal AI</title></head>"
        "<body style='font-family:sans-serif;display:flex;height:100vh;align-items:center;"
        "justify-content:center;background:#141311;color:#eee'>"
        f"<p>{safe_message} You can close this window.</p>"
        "<script>"
        f"try{{window.opener&&window.opener.postMessage({payload},'*');}}catch(e){{}}"
        "setTimeout(function(){window.close();},800);"
        "</script></body></html>"
    )


@router.get("/connectors/{service}/oauth/callback", response_class=HTMLResponse)
async def oauth_callback(
    service: str,
    db: DB,
    code: str = "",
    state: str = "",
    error: str = "",
    error_description: str = "",
):
    """Provider redirect target (no auth: the popup carries no token).
    Exchanges the code, verifies the account, stores tokens encrypted."""
    from app.connectors import exchange_oauth_code

    if error or not code:
        return _oauth_page(
            ok=False, service=service,
            message=error_description or error or "Authorization was not granted.",
        )
    meta = SERVICES.get(service)
    if not meta:
        return _oauth_page(ok=False, service=service, message="Unknown service.")
    try:
        result = await exchange_oauth_code(service, code=code, state_id=state)
        access = str(result["tokens"]["access_token"])
        build = meta.get("build") or (lambda token, extra: meta["client"](token))
        account = await build(access, {}).whoami()
        if not isinstance(account, dict):
            account = {"result": account}
        account["_oauth"] = {
            "service": service,
            "expires_at": result["vault"].get("expires_at", 0),
            "has_refresh": bool(result["vault"].get("refresh_token")),
        }
        account["_vault"] = encrypt(json.dumps(result["vault"]))
        row = (
            await db.execute(select(Connector).where(Connector.service == service))
        ).scalar_one_or_none()
        if row:
            row.token_enc = encrypt(access)
            row.account = account
            row.enabled = True
        else:
            db.add(Connector(service=service, token_enc=encrypt(access), account=account))
        await db.commit()
        label = str(account.get("username") or account.get("name") or account.get("user") or service)
        return _oauth_page(ok=True, service=service, message=f"{meta['label']} connected as {label}.")
    except AppError as exc:
        return _oauth_page(ok=False, service=service, message=str(exc))
    except Exception as exc:
        log.warning("oauth callback for %s failed: %s", service, exc)
        return _oauth_page(ok=False, service=service, message="Verification failed — token rejected.")


# ---------------------------------------------------------------------------
# MCP
# ---------------------------------------------------------------------------


class MCPIn(BaseModel):
    name: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_-]+$")
    transport: str = Field(default="stdio", pattern="^(stdio|sse|http)$")
    command: str = ""
    args: list[str] = Field(default_factory=list)
    url: str = ""
    env: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)

    def remote_url(self) -> str:
        if self.transport in ("sse", "http") and self.url:
            from app.core.net import assert_public_url

            # Direct user-typed MCP URL: allow loopback (local SSE servers)
            # but still block LAN + cloud metadata. Registry installs below
            # stay strict (third-party URLs).
            assert_public_url(self.url, allow_loopback=True)
        return self.url


MCP_PRESETS = [
    {"name": "filesystem", "transport": "stdio", "command": "npx",
     "args": ["-y", "@modelcontextprotocol/server-filesystem", "/workspace"]},
    {"name": "fetch", "transport": "stdio", "command": "uvx", "args": ["mcp-server-fetch"]},
    {"name": "memory", "transport": "stdio", "command": "npx",
     "args": ["-y", "@modelcontextprotocol/server-memory"]},
    {"name": "sequentialthinking", "transport": "stdio", "command": "npx",
     "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"]},
    {"name": "playwright", "transport": "stdio", "command": "npx",
     "args": ["-y", "@playwright/mcp@latest"]},
]


async def _record_mcp_start(server_name: str, conn) -> None:
    """Finish a prepared MCP supervisor in the background (npx downloads can
    take a minute) and persist the outcome, keeping the HTTP request fast."""
    from app.db.session import SessionLocal

    try:
        state = await mcp_manager.finish(conn)
    except Exception as exc:
        log.warning("background MCP start for %s failed: %s", server_name, exc)
        return
    try:
        async with SessionLocal() as db2:
            row = (
                await db2.execute(select(MCPServer).where(MCPServer.name == server_name))
            ).scalar_one_or_none()
            if row is not None:
                row.last_error = state.error
                row.tool_count = len(state.tools)
                await db2.commit()
    except Exception as exc:
        log.warning("could not persist MCP start outcome for %s: %s", server_name, exc)


def serialize_mcp(row: MCPServer) -> dict:
    state = mcp_manager.state(row.name)
    return {
        "id": row.id,
        "name": row.name,
        "transport": row.transport,
        "command": row.command,
        "args": row.args or [],
        "url": row.url,
        "env": {k: "***" for k in (row.env or {})},
        "headers": {k: "***" for k in (row.headers or {})},
        "enabled": row.enabled,
        "status": state.status if state else ("stopped" if row.enabled else "disabled"),
        "error": state.error if state else row.last_error,
        "tools": [
            {"name": t.qualified, "original": t.name, "description": t.description}
            for t in (state.tools if state else [])
        ],
        "updated_at": iso(row.updated_at),
    }


@router.get("/mcp/presets")
async def mcp_presets(_: Auth):
    return MCP_PRESETS


class RegistryInstallIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


@router.get("/mcp/registry")
async def mcp_registry(_: Auth, search: str = "", limit: int = 30, offset: int = 0):
    """Search the official MCP Registry (registry.modelcontextprotocol.io)."""
    from app.mcp.registry import search_servers

    return await search_servers(search, limit, offset)


@router.get("/mcp/registry/{name:path}")
async def mcp_registry_detail(name: str, _: Auth):
    """Latest version detail for one registry server (URL-encoded name)."""
    from app.mcp.registry import build_install_config, server_detail

    detail = await server_detail(name)
    return {**detail, "install_config": build_install_config(detail)}


@router.post("/mcp/registry/install", status_code=201)
async def mcp_registry_install(body: RegistryInstallIn, db: DB, _: Auth):
    """One-click install from the official registry (stdio npm/uvx or remote)."""
    from app.mcp.registry import build_install_config, server_detail

    detail = await server_detail(body.name)
    config = build_install_config(detail)
    if config.get("transport") in ("sse", "http") and config.get("url"):
        from app.core.net import assert_public_url

        assert_public_url(config["url"])

    row = (
        await db.execute(select(MCPServer).where(MCPServer.name == config["name"]))
    ).scalar_one_or_none()
    if row is None:
        row = MCPServer(name=config["name"])
        db.add(row)
    row.transport = config["transport"]
    row.command = config["command"]
    row.args = config["args"]
    row.url = config["url"]
    row.env = config["env"]
    row.enabled = True
    await db.commit()

    conn = await mcp_manager.prepare(
        {
            "name": row.name, "transport": row.transport, "command": row.command,
            "args": row.args or [], "url": row.url, "env": row.env or {}, "headers": {},
        }
    )
    asyncio.create_task(_record_mcp_start(row.name, conn))
    return {**serialize_mcp(row), "registry_notes": config.get("notes", "")}


class DirectoryInstallIn(BaseModel):
    slug: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9-]+$")
    name: str = Field(default="", max_length=60)


@router.get("/mcp/directory")
async def mcp_directory(_: Auth, search: str = "", limit: int = 30):
    """Second marketplace: mcpservers.org remote (hosted) MCP servers."""
    from app.mcp.directory import search_servers

    return search_servers(search, limit)


@router.get("/mcp/directory/{slug}")
async def mcp_directory_detail(slug: str, _: Auth):
    """Connection details for one directory entry."""
    from app.mcp.directory import build_install_config, server_detail

    detail = server_detail(slug)
    return {**detail, "install_config": build_install_config(detail)}


@router.post("/mcp/directory/install", status_code=201)
async def mcp_directory_install(body: DirectoryInstallIn, db: DB, _: Auth):
    """One-click install of a hosted server (http/sse, no local package)."""
    from app.mcp.directory import build_install_config, server_detail

    detail = server_detail(body.slug)
    config = build_install_config(detail, body.name or detail["slug"])
    if config.get("url"):
        from app.core.net import assert_public_url

        assert_public_url(config["url"])

    row = (
        await db.execute(select(MCPServer).where(MCPServer.name == config["name"]))
    ).scalar_one_or_none()
    if row is None:
        row = MCPServer(name=config["name"])
        db.add(row)
    row.transport = config["transport"]
    row.command = ""
    row.args = []
    row.url = config["url"]
    row.env = {}
    row.enabled = True
    await db.commit()

    conn = await mcp_manager.prepare(
        {
            "name": row.name, "transport": row.transport, "command": "",
            "args": [], "url": row.url, "env": {}, "headers": {},
        }
    )
    asyncio.create_task(_record_mcp_start(row.name, conn))
    return {**serialize_mcp(row), "registry_notes": config.get("notes", "")}


@router.get("/mcp")
async def list_mcp(db: DB, _: Auth):
    rows = (await db.execute(select(MCPServer).order_by(MCPServer.name))).scalars().all()
    return [serialize_mcp(r) for r in rows]


@router.post("/mcp", status_code=201)
async def add_mcp(body: MCPIn, db: DB, _: Auth):
    if body.transport == "stdio" and not body.command:
        raise AppError("stdio servers need a command")
    if body.transport in ("sse", "http") and not body.url:
        raise AppError(f"{body.transport} servers need a url")
    body.remote_url()

    row = (
        await db.execute(select(MCPServer).where(MCPServer.name == body.name))
    ).scalar_one_or_none()
    if row is None:
        row = MCPServer(name=body.name)
        db.add(row)
    row.transport = body.transport
    row.command = body.command
    row.args = body.args
    row.url = body.url
    # serialize_mcp() masks secrets as "***" — never persist the placeholder
    # over a real secret when the UI round-trips the masked object.
    row.env = _merge_secret_dict(dict(row.env or {}), body.env)
    row.headers = _merge_secret_dict(dict(row.headers or {}), body.headers)
    row.enabled = True
    await db.commit()

    config = body.model_dump()
    config["env"] = row.env
    config["headers"] = row.headers
    conn = await mcp_manager.prepare(config)
    asyncio.create_task(_record_mcp_start(row.name, conn))
    return serialize_mcp(row)


@router.post("/mcp/{name}/restart")
async def restart_mcp(name: str, db: DB, _: Auth):
    row = (await db.execute(select(MCPServer).where(MCPServer.name == name))).scalar_one_or_none()
    if not row:
        raise NotFound(f"MCP server {name} not found")
    conn = await mcp_manager.prepare(
        {
            "name": row.name, "transport": row.transport, "command": row.command,
            "args": row.args or [], "url": row.url, "env": row.env or {}, "headers": row.headers or {},
        }
    )
    asyncio.create_task(_record_mcp_start(row.name, conn))
    return serialize_mcp(row)


@router.delete("/mcp/{name}")
async def remove_mcp(name: str, db: DB, _: Auth):
    await mcp_manager.stop(name)
    row = (await db.execute(select(MCPServer).where(MCPServer.name == name))).scalar_one_or_none()
    if row:
        await db.delete(row)
        await db.commit()
    return {"deleted": name}
