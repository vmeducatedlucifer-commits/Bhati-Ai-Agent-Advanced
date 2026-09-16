"""Second MCP marketplace: mcpservers.org remote directory.

The official registry (registry.py) stays as-is; this is an additional source
of *hosted* (no local install) MCP servers. The site exposes no JSON API, so
the static listing/detail HTML is parsed with tolerant regexes and cached.
Every entry resolves to an http/sse endpoint + auth notes before install.
"""

from __future__ import annotations

import html as html_lib
import re
import time
from typing import Any
from urllib.parse import quote

import httpx

from app.core.errors import AppError
from app.core.logging import get_logger

log = get_logger("app.mcp.directory")

BASE_URL = "https://mcpservers.org"
CACHE_TTL = 3600

_cache: dict[str, tuple[float, Any]] = {}

CARD_RE = re.compile(
    r'<a href="/remote-mcp-servers/([a-z0-9-]+)"[^>]*>.*?'
    r'<div class="truncate text-sm font-semibold[^"]*">([^<]+)</div>'
    r'<div class="truncate text-xs[^"]*">([^<]*)</div>',
    re.DOTALL,
)
CODE_RE = re.compile(r"<code[^>]*>(https?://[^<]+)</code>")
DT_RE = re.compile(
    r"<dt[^>]*>\s*(Transport|Authentication)\s*</dt>\s*<dd[^>]*>([^<]+)</dd>"
)


def _cache_get(key: str) -> Any | None:
    entry = _cache.get(key)
    if entry and time.time() - entry[0] < CACHE_TTL:
        return entry[1]
    _cache.pop(key, None)
    return None


def _cache_set(key: str, value: Any) -> None:
    _cache[key] = (time.time(), value)
    if len(_cache) > 100:
        _cache.pop(next(iter(_cache)))


def _fetch_text(url: str, limit: int = 2_000_000) -> str:
    from urllib.parse import urljoin as _urljoin

    from app.core.net import assert_public_url

    assert_public_url(url)
    try:
        current = url
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            for _ in range(6):
                with client.stream(
                    "GET", current, headers={"User-Agent": "BhatiAiAgent/2.0"}
                ) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location", "")
                        if not location:
                            raise AppError("Redirect without location", code="directory_down")
                        current = _urljoin(current, location)
                        assert_public_url(current)
                        continue
                    response.raise_for_status()
                    assert_public_url(str(response.url))
                    chunks: list[bytes] = []
                    total = 0
                    for chunk in response.iter_bytes(65536):
                        total += len(chunk)
                        if total > limit:
                            raise AppError("Directory page too large", code="too_large")
                        chunks.append(chunk)
                    return b"".join(chunks).decode("utf-8", errors="ignore")
            raise AppError("Too many redirects", code="directory_down")
    except AppError:
        raise
    except Exception as exc:
        raise AppError(f"Directory unreachable: {exc}", code="directory_down") from exc


def _clean(text: str) -> str:
    return html_lib.unescape(text).strip()


def list_servers() -> list[dict[str, Any]]:
    """All remote servers from the directory listing (cached 1h)."""
    cached = _cache_get("listing")
    if cached is not None:
        return cached
    html = _fetch_text(f"{BASE_URL}/remote-mcp-servers")
    servers: dict[str, dict[str, Any]] = {}
    for slug, name, blurb in CARD_RE.findall(html):
        if slug in servers:
            continue
        servers[slug] = {
            "slug": slug,
            "name": _clean(name),
            "description": _clean(blurb)[:300],
            "url": f"{BASE_URL}/remote-mcp-servers/{slug}",
        }
    result = sorted(servers.values(), key=lambda s: s["name"].lower())
    log.info("mcpservers.org directory: %d servers", len(result))
    _cache_set("listing", result)
    return result


def search_servers(query: str = "", limit: int = 30) -> dict[str, Any]:
    """Search the directory (client filters further too)."""
    servers = list_servers()
    if query.strip():
        needle = query.strip().lower()
        servers = [
            s
            for s in servers
            if needle in s["slug"].lower()
            or needle in s["name"].lower()
            or needle in s["description"].lower()
        ]
    return {"servers": servers[: max(1, min(limit, 100))], "count": len(servers)}


def server_detail(slug: str) -> dict[str, Any]:
    """Connection details (endpoint URL, transport, auth) for one entry."""
    if not re.fullmatch(r"[a-z0-9-]+", slug):
        raise AppError("Invalid directory entry", code="bad_name")
    cache_key = f"detail:{slug}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    html = _fetch_text(f"{BASE_URL}/remote-mcp-servers/{quote(slug)}")
    section = html.split("Connection details", 1)
    if len(section) < 2:
        raise AppError(
            f"No connection details published for '{slug}'", code="not_installable"
        )
    block = section[1][:6000]
    code = CODE_RE.search(block)
    if not code:
        raise AppError(
            f"No endpoint published for '{slug}'", code="not_installable"
        )
    fields = {
        _clean(k).lower(): _clean(v) for k, v in DT_RE.findall(block)
    }
    transport_raw = fields.get("transport", "").lower()
    transport = "sse" if "sse" in transport_raw else "http"
    detail = {
        "slug": slug,
        "endpoint": _clean(code.group(1)),
        "transport": transport,
        "transport_label": fields.get("transport", transport),
        "auth": fields.get("authentication", "Unknown"),
    }
    _cache_set(cache_key, detail)
    return detail


def build_install_config(detail: dict[str, Any], name: str = "") -> dict[str, Any]:
    """Directory detail → our MCPServer config (remote http/sse, no local pkg)."""
    short = (
        re.sub(r"[^a-z0-9-]", "-", (name or detail.get("slug", "remote")).lower())
        .strip("-")[:60]
        or "remote-mcp"
    )
    return {
        "name": short,
        "transport": detail.get("transport", "http"),
        "command": "",
        "args": [],
        "url": detail.get("endpoint", ""),
        "env": {},
        "notes": f"{detail.get('transport_label', '')} · auth: {detail.get('auth', '?')} — add credentials in env if the server rejects anonymous calls",
    }
