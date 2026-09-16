"""Official MCP Registry client (registry.modelcontextprotocol.io).

Proxies the public registry REST API and normalizes server.json metadata into
installable configs for our MCP manager (stdio via npm/uvx, or remote SSE/HTTP).
Responses are cached briefly to respect the registry's polling guidance.
"""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import quote

import httpx

from app.core.errors import AppError
from app.core.logging import get_logger

log = get_logger("app.mcp.registry")

BASE_URL = "https://registry.modelcontextprotocol.io"
CACHE_TTL = 600

_cache: dict[str, tuple[float, Any]] = {}


def _cache_get(key: str) -> Any | None:
    entry = _cache.get(key)
    if entry and time.time() - entry[0] < CACHE_TTL:
        return entry[1]
    _cache.pop(key, None)
    return None


def _cache_set(key: str, value: Any) -> None:
    _cache[key] = (time.time(), value)
    if len(_cache) > 200:
        _cache.pop(next(iter(_cache)))


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    url = f"{BASE_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, params=params or {})
            response.raise_for_status()
            return response.json()
    except Exception as exc:
        raise AppError(f"MCP registry unreachable: {exc}", code="registry_down") from exc


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _first_package_by_type(packages: list[Any], *types: str) -> dict[str, Any] | None:
    for package in packages:
        if not isinstance(package, dict):
            continue
        registry_type = str(
            package.get("registryType") or package.get("registry_type") or ""
        ).lower()
        if registry_type in types:
            return package
    return None


def normalize_entry(item: dict[str, Any]) -> dict[str, Any]:
    """Flatten a registry server entry (list or detail shape) for the UI."""
    server = item.get("server", item) if isinstance(item, dict) else {}
    if not isinstance(server, dict):
        server = {}
    name = str(server.get("name", ""))
    description = str(server.get("description", ""))
    version = str(item.get("version") or server.get("version") or "")
    repository = server.get("repository") or {}
    repo_url = str(repository.get("url", "")) if isinstance(repository, dict) else ""
    packages = _as_list(server.get("packages"))
    remotes = _as_list(server.get("remotes"))

    transports: list[str] = []
    for remote in remotes:
        if isinstance(remote, dict):
            kind = str(remote.get("type", remote.get("transport", ""))).lower().replace("_", "-")
            if kind in ("streamable-http", "sse", "http") and kind not in transports:
                transports.append("http" if kind == "streamable-http" else kind)
    if _first_package_by_type(packages, "npm", "pypi", "nuget", "oci", "mcpb") and "stdio" not in transports:
        transports.append("stdio")

    return {
        "name": name,
        "description": description[:300],
        "version": version,
        "repository": repo_url,
        "transports": transports,
        "package_count": len(packages),
        "remote_count": len(remotes),
    }


async def search_servers(query: str = "", limit: int = 30, offset: int = 0) -> dict[str, Any]:
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    cache_key = f"search:{query}:{limit}:{offset}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if query.strip():
        params["search"] = query.strip()
    try:
        data = await _get("/v0/servers", params)
    except AppError:
        # Older deployments expose /v0.1 — fall back transparently.
        data = await _get("/v0.1/servers", params)
    servers = [normalize_entry(item) for item in _as_list(data.get("servers"))]
    if query.strip():
        needle = query.strip().lower()
        servers = [s for s in servers if needle in s["name"].lower() or needle in s["description"].lower()]
    # The registry lists every published version separately — collapse
    # duplicates by name (keep the highest version) so the UI shows one
    # installable row per server.
    by_name: dict[str, dict[str, Any]] = {}
    for server in servers:
        prev = by_name.get(server["name"])
        if prev is None or _version_tuple(server["version"]) > _version_tuple(prev["version"]):
            by_name[server["name"]] = server
    servers = sorted(by_name.values(), key=lambda s: s["name"].lower())
    result = {"servers": servers, "count": len(servers)}
    _cache_set(cache_key, result)
    return result


def _version_tuple(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in re.split(r"[.\-+]", version or "")[:4]:
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


async def server_detail(name: str) -> dict[str, Any]:
    """Fetch the latest version detail for a registry server name."""
    cache_key = f"detail:{name}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    encoded = quote(name, safe="")
    try:
        data = await _get(f"/v0/servers/{encoded}/versions/latest")
    except AppError:
        data = await _get(f"/v0.1/servers/{encoded}/versions/latest")
    detail = _parse_detail(data, name)
    _cache_set(cache_key, detail)
    return detail


def _parse_detail(data: Any, name: str) -> dict[str, Any]:
    """Normalize the detail payload (single-object or list shape) or raise."""
    if isinstance(data, dict) and isinstance(data.get("server"), dict):
        # Single-object shape: {"server": {...}, "version": "...", "_meta": {...}}.
        server = data["server"]
        if server.get("name"):
            detail = dict(server)
            detail["_version"] = data.get("version") or server.get("version", "")
            return detail
    for item in _as_list(data.get("servers") if isinstance(data, dict) else None):
        server = item.get("server", item)
        if isinstance(server, dict) and server.get("name"):
            detail = dict(server)
            detail["_version"] = item.get("version") or server.get("version", "")
            return detail
    raise AppError(f"Server not found in registry: {name}", code="not_found", status_code=404)


def _package_args(package: dict[str, Any]) -> list[str]:
    args = package.get("arguments") or package.get("args") or []
    return [str(a) for a in args] if isinstance(args, list) else []


def build_install_config(detail: dict[str, Any]) -> dict[str, Any]:
    """Convert registry detail into our MCPServer config (transport/cmd/url/env)."""
    name = str(detail.get("name", "mcp-server"))
    short = name.split("/")[-1].replace("_", "-")[:60] or "mcp-server"
    packages = _as_list(detail.get("packages"))
    remotes = _as_list(detail.get("remotes"))

    npm = _first_package_by_type(packages, "npm")
    if npm:
        identifier = str(npm.get("identifier") or npm.get("name") or short)
        version = str(npm.get("version") or "latest")
        args = _package_args(npm)
        return {
            "name": short, "transport": "stdio",
            "command": "npx", "args": ["-y", f"{identifier}@{version}", *args],
            "url": "", "env": _env_template(detail), "notes": f"npm {identifier}@{version}",
        }
    pypi = _first_package_by_type(packages, "pypi")
    if pypi:
        identifier = str(pypi.get("identifier") or pypi.get("name") or short)
        args = _package_args(pypi)
        return {
            "name": short, "transport": "stdio",
            "command": "uvx", "args": [identifier, *args],
            "url": "", "env": _env_template(detail), "notes": f"pypi {identifier}",
        }
    for remote in remotes:
        if not isinstance(remote, dict):
            continue
        kind = str(remote.get("type", remote.get("transport", ""))).lower().replace("_", "-")
        url = str(remote.get("url", ""))
        if url and kind in ("streamable-http", "http"):
            return {"name": short, "transport": "http", "command": "", "args": [],
                    "url": url, "env": _env_template(detail), "notes": f"remote {kind}"}
        if url and kind == "sse":
            return {"name": short, "transport": "sse", "command": "", "args": [],
                    "url": url, "env": _env_template(detail), "notes": "remote sse"}
    raise AppError(
        "Registry entry has no installable npm/pypi package or remote URL",
        code="not_installable",
    )


def _env_template(detail: dict[str, Any]) -> dict[str, str]:
    env: dict[str, str] = {}
    raw = detail.get("environment_variables") or detail.get("env") or []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and item.get("name"):
                env[str(item["name"])] = ""
            elif isinstance(item, str):
                env[item] = ""
    elif isinstance(raw, dict):
        for key in raw:
            env[str(key)] = ""
    return env
