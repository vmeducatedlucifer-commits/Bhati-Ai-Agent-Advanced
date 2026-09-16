"""Append-only audit trail for significant user actions."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.models import AuditLog

log = get_logger("app.audit")


async def record(db: AsyncSession, action: str, detail: dict[str, Any] | None = None, actor: str = "local") -> None:
    try:
        db.add(AuditLog(actor=actor, action=action, detail=detail or {}))
        await db.commit()
    except Exception as exc:
        await db.rollback()
        log.warning("audit record failed (%s): %s", action, exc)
