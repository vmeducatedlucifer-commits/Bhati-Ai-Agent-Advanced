"""Optional single-password auth."""

from __future__ import annotations

import math
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.deps import DB, Auth
from app.core.audit import record
from app.core.config import settings
from app.core.errors import Unauthorized
from app.core.security import create_token, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

# In-memory login brute-force brake. Two layers because the per-identity key
# alone is NOT enough:
#   1. Per-key: 5 failures / 5 min → escalating lockout for that key.
#   2. Global: 30 failures / 5 min across ALL keys → 429 for everyone.
# Layer 2 exists because X-Forwarded-For's first entry is attacker-controlled:
# rotating it (`X-Forwarded-For: 1.2.3.<i>` per guess) makes every attempt look
# like a new IP, so a per-IP limit alone can be bypassed with one header.
# The global bucket caps total guessing at ~360/hour no matter the spoofing.
# No new dependency; resets on restart (acceptable for a single-instance
# self-hosted gate — an attacker cannot force a restart to clear it).
_LOGIN_FAILURES: dict[str, list[float]] = {}
_GLOBAL_FAILURES: list[float] = []
_BLOCKED_UNTIL: dict[str, float] = {}
_LOCKOUT_STRIKES: dict[str, int] = {}
LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_S = 300
GLOBAL_MAX_FAILURES = 30
GLOBAL_WINDOW_S = 300
BASE_BLOCK_S = 300
MAX_BLOCK_S = 7200
MAX_TRACKED_KEYS = 1000


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "unknown")[:64]


def _prune(now: float) -> None:
    global _GLOBAL_FAILURES
    _GLOBAL_FAILURES = [t for t in _GLOBAL_FAILURES if now - t < GLOBAL_WINDOW_S]
    dead = [
        ip for ip, attempts in _LOGIN_FAILURES.items()
        if not [t for t in attempts if now - t < LOGIN_WINDOW_S]
        and _BLOCKED_UNTIL.get(ip, 0) <= now
    ]
    for ip in dead:
        _LOGIN_FAILURES.pop(ip, None)
        _LOCKOUT_STRIKES.pop(ip, None)
        _BLOCKED_UNTIL.pop(ip, None)
    if len(_LOGIN_FAILURES) > MAX_TRACKED_KEYS:
        # Spoofed-key flood: drop the stalest keys first.
        for ip in sorted(_LOGIN_FAILURES, key=lambda k: _LOGIN_FAILURES[k][-1] if _LOGIN_FAILURES[k] else 0)[: len(_LOGIN_FAILURES) - MAX_TRACKED_KEYS]:
            _LOGIN_FAILURES.pop(ip, None)
            _LOCKOUT_STRIKES.pop(ip, None)
            _BLOCKED_UNTIL.pop(ip, None)


def _block_seconds(strikes: int) -> int:
    return min(BASE_BLOCK_S * (2 ** strikes), MAX_BLOCK_S)


def _record_failure(ip: str, now: float) -> None:
    _LOGIN_FAILURES.setdefault(ip, []).append(now)
    _GLOBAL_FAILURES.append(now)
    if len(_LOGIN_FAILURES) > MAX_TRACKED_KEYS or len(_GLOBAL_FAILURES) > GLOBAL_MAX_FAILURES * 4:
        _prune(now)


def _lockout_remaining(ip: str, now: float) -> float:
    """Seconds the key must wait, or 0. Arms escalating lockouts."""
    _prune(now)
    remaining = _BLOCKED_UNTIL.get(ip, 0) - now
    if remaining > 0:
        return remaining
    key_attempts = _LOGIN_FAILURES.get(ip, [])
    if len(key_attempts) >= LOGIN_MAX_FAILURES or len(_GLOBAL_FAILURES) >= GLOBAL_MAX_FAILURES:
        strikes = _LOCKOUT_STRIKES.get(ip, 0)
        block = _block_seconds(strikes)
        _BLOCKED_UNTIL[ip] = now + block
        _LOCKOUT_STRIKES[ip] = strikes + 1
        return float(block)
    return 0.0


def _reset_key(ip: str) -> None:
    _LOGIN_FAILURES.pop(ip, None)
    _BLOCKED_UNTIL.pop(ip, None)
    _LOCKOUT_STRIKES.pop(ip, None)


def _rate_limited_response(retry_after_s: float) -> JSONResponse:
    seconds = max(1, int(math.ceil(retry_after_s)))
    mins = max(1, math.ceil(seconds / 60))
    return JSONResponse(
        status_code=429,
        content={"error": {"code": "rate_limited", "message": f"Too many attempts — try again in ~{mins} min"}},
        headers={"Retry-After": str(seconds)},
    )


class LoginBody(BaseModel):
    password: str
    username: str = ""


@router.get("/status")
async def status():
    return {"auth_required": settings.auth_enabled, "username": settings.AUTH_USERNAME}


@router.post("/login")
async def login(body: LoginBody, db: DB, request: Request):
    ip = _client_ip(request)
    now = time.time()
    if not settings.auth_enabled:
        return {"token": create_token("local"), "username": "local"}
    # Correct password always works, even mid-lockout: this denies an attacker
    # the ability to lock the real owner out, and costs the attacker nothing
    # either way (a correct guess ends the game regardless of throttling).
    if verify_password(body.password):
        _reset_key(ip)
        await record(db, "auth.login", {"username": settings.AUTH_USERNAME})
        return {"token": create_token(settings.AUTH_USERNAME), "username": settings.AUTH_USERNAME}
    _record_failure(ip, now)
    limited_for = _lockout_remaining(ip, now)
    await record(db, "auth.failed", {
        "username": body.username or settings.AUTH_USERNAME,
        "ip": ip,
        "limited": limited_for > 0,
    })
    if limited_for > 0:
        return _rate_limited_response(limited_for)
    raise Unauthorized("Wrong password")


@router.get("/me")
async def me(subject: Auth):
    return {"username": subject, "auth_required": settings.auth_enabled}


@router.post("/logout")
async def logout(db: DB, subject: Auth):
    """Server-acknowledged logout: the client drops its token, and supporting
    browsers wipe site data (disk/memory cache, storage) on this response, so
    no conversation residue survives on the machine after sign-out."""
    await record(db, "auth.logout", {"username": subject})
    return JSONResponse(
        status_code=200,
        content={"logged_out": True},
        headers={"Clear-Site-Data": '"cache", "storage"'},
    )
