"""JWT issuing and verification."""

from __future__ import annotations

import datetime as dt
import hmac
from typing import Any

import jwt

from app.core.config import settings


def create_token(subject: str, extra: dict[str, Any] | None = None) -> str:
    now = dt.datetime.now(dt.UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "iss": settings.JWT_ISSUER,
        "aud": settings.JWT_AUDIENCE,
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(hours=settings.JWT_TTL_HOURS)).timestamp()),
        **(extra or {}),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            issuer=settings.JWT_ISSUER,
            audience=settings.JWT_AUDIENCE,
        )
    except jwt.PyJWTError:
        return None


def verify_password(candidate: str) -> bool:
    """Constant-time comparison against the configured shared password."""
    if not settings.AUTH_PASSWORD:
        return True
    return hmac.compare_digest(candidate.strip().encode("utf-8"), settings.AUTH_PASSWORD.strip().encode("utf-8"))
