"""Embedded model gateway configuration.

Runs ONLY on loopback inside the same container/host as the agent backend and
accepts calls ONLY from the agent (shared-secret Bearer). It is never exposed
to the public internet: Render routes a single public port to the agent API,
and this gateway binds 127.0.0.1 by default (see start.sh).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List


# Model ids the embedded gateway serves. Frontend shows friendly aliases
# ("General"/"Pro") — the raw ids never leave the backend.
BUILTIN_GENERAL_MODEL = "gemini-2.0-flash"
BUILTIN_PRO_MODEL = "gemini-1.5-pro"
BUILTIN_MODELS: tuple[str, ...] = (BUILTIN_GENERAL_MODEL, BUILTIN_PRO_MODEL)


@dataclass
class GatewaySettings:
    # ---- loopback bind (never 0.0.0.0) -----------------------------------
    host: str = os.getenv("GATEWAY_HOST", "127.0.0.1")
    port: int = int(os.getenv("GATEWAY_PORT", "8081"))
    # ---- agent-only auth --------------------------------------------------
    # Shared secret the agent sends as `Authorization: Bearer <secret>`.
    # Empty ONLY for local dev (loopback still isolates it). Prod refuses to
    # boot without a real value (see app.main lifespan guard).
    shared_secret: str = os.getenv("GATEWAY_SHARED_SECRET", "")

    # ---- upstream (Google web tunnel, keyless) -----------------------------
    stream_bl: str = os.getenv(
        "STREAM_BL", "boq_assistant-bard-web-server_20260716.08_p0"
    )
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", os.getenv("GEMINI_API_KEYS", os.getenv("GEMINI_KEYS", "")))
    gemini_cookie: str = os.getenv("GEMINI_COOKIE", os.getenv("GEMINI_COOKIES", os.getenv("GEMINI_COOKIE_POOL", "")))
    gemini_sapisid: str = os.getenv("GEMINI_SAPISID", "")
    gemini_at: str = os.getenv("GEMINI_AT", "")
    user_agent: str = os.getenv(
        "USER_AGENT",
        "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/133.0.0.0 Mobile Safari/537.36",
    )
    default_model: str = os.getenv("DEFAULT_MODEL", BUILTIN_GENERAL_MODEL)
    request_timeout: float = float(os.getenv("REQUEST_TIMEOUT", "180"))
    upstream_proxy: str = os.getenv("UPSTREAM_PROXY", os.getenv("HTTPS_PROXY", os.getenv("HTTP_PROXY", "")))
    browser_impersonate: str = os.getenv("BROWSER_IMPERSONATE", "chrome124")
    session_ttl: int = int(os.getenv("SESSION_TTL", "1800"))
    session_pool_size: int = int(os.getenv("SESSION_POOL_SIZE", "5"))
    rotate_session_every_request: bool = os.getenv("ROTATE_SESSION", "1") == "1"
    max_requests_per_session: int = int(os.getenv("MAX_REQUESTS_PER_SESSION", "15"))
    session_cooldown_seconds: int = int(os.getenv("SESSION_COOLDOWN_SECONDS", "60"))
    max_retries: int = int(os.getenv("MAX_RETRIES", "3"))

    def get_api_keys(self) -> List[str]:
        raw = self.gemini_api_key or ""
        keys = [k.strip() for k in raw.replace("\n", ",").split(",") if k.strip()]
        return keys

    def get_cookies(self) -> List[str]:
        raw = self.gemini_cookie or ""
        if "|||" in raw:
            cookies = [c.strip() for c in raw.split("|||") if c.strip()]
        elif "\n" in raw:
            cookies = [c.strip() for c in raw.split("\n") if c.strip()]
        else:
            cookies = [raw.strip()] if raw.strip() else []
        return cookies


settings = GatewaySettings()
