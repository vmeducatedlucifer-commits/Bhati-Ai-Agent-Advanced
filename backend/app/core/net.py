"""Outbound URL safety: stop server-side requests reaching private networks.

Every feature that fetches a user-controlled URL (skill installs, provider
probes, web_fetch, MCP remote servers) must pass through assert_public_url
so a malicious URL cannot reach cloud metadata (169.254.169.254), loopback
services, or the LAN. Hostnames are resolved and every answer checked —
only globally routable IPs pass.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from app.core.errors import AppError

_LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".localdomain", ".invalid", ".test")


def _blocked(reason: str) -> AppError:
    return AppError(f"Blocked {reason}", code="private_host")


def _is_loopback_host(host: str, ip: ipaddress.IPv4Address | ipaddress.IPv6Address | None) -> bool:
    if host == "localhost":
        return True
    if ip is not None:
        return ip.is_loopback
    return False


def assert_public_url(url: str, *, allow_loopback: bool = False) -> str:
    """Validate that fetching `url` cannot hit non-public infrastructure.

    `allow_loopback=True` permits localhost/loopback (Ollama, local MCP SSE)
    while still blocking LAN, cloud metadata (169.254.x.x) and other private
    ranges. Use it only for URLs the authenticated user typed explicitly
    (provider base_url, direct MCP add) — never for agent/third-party URLs
    (skill installs, registry installs, web_fetch).
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise AppError("Only http(s) URLs are allowed", code="bad_url")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host:
        raise AppError("URL has no host", code="bad_url")
    if host == "localhost" or host.endswith(_LOCAL_SUFFIXES):
        if allow_loopback and (host == "localhost" or host.endswith(".localhost")):
            pass  # explicit local dev override below still checks DNS
        else:
            raise _blocked(f"local name '{host}'")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if ip.is_loopback and allow_loopback:
            return url
        if not ip.is_global:
            raise _blocked(f"non-public IP '{host}'")
        return url
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        raise AppError(f"Cannot resolve host '{host}'", code="bad_url")
    if not infos:
        raise AppError(f"Cannot resolve host '{host}'", code="bad_url")
    for info in infos:
        try:
            resolved = ipaddress.ip_address(info[4][0])
        except ValueError:
            continue
        if resolved.is_loopback and allow_loopback:
            continue
        if not resolved.is_global:
            raise _blocked(f"host '{host}' resolves to non-public IP")
    return url
