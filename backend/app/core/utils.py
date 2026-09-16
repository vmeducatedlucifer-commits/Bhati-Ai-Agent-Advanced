"""Small helpers shared across modules."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime
from uuid import uuid4


def new_id(prefix: str = "") -> str:
    raw = uuid4().hex[:24]
    return f"{prefix}_{raw}" if prefix else raw


def utcnow() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def slugify(value: str, fallback: str = "project") -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value or fallback


def truncate(text: str, limit: int, note: str = "\n… (truncated)") -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + note


def human_bytes(size: int) -> str:
    step = 1024.0
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < step:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= step
    return f"{size:.1f} PB"
