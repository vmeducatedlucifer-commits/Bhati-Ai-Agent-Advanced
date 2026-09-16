"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header, Query, WebSocket
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import NotFound, Unauthorized
from app.core.security import decode_token
from app.db.models import Project, Thread
from app.db.session import SessionLocal


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


DB = Annotated[AsyncSession, Depends(get_db)]


def _token_from(authorization: str | None, token: str | None) -> str:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return (token or "").strip()


async def require_auth(
    authorization: Annotated[str | None, Header()] = None,
    token: Annotated[str | None, Query()] = None,
) -> str:
    """Returns the subject. When AUTH_PASSWORD is unset the app runs open (local mode)."""
    if not settings.auth_enabled:
        return "local"
    payload = decode_token(_token_from(authorization, token))
    if not payload:
        raise Unauthorized("Sign in to continue")
    return str(payload.get("sub", "user"))


Auth = Annotated[str, Depends(require_auth)]


async def require_ws_auth(websocket: WebSocket) -> str:
    if not settings.auth_enabled:
        return "local"
    token = websocket.query_params.get("token", "")
    payload = decode_token(token)
    if not payload:
        await websocket.close(code=4401)
        raise Unauthorized("Sign in to continue")
    return str(payload.get("sub", "user"))


async def get_project(db: AsyncSession, project_id: str) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise NotFound(f"Project {project_id} not found")

    # If workspace is empty or missing locally, restore from Google Drive
    try:
        from pathlib import Path

        from app.storage import gdrive_manager
        ws = Path(project.workspace_path)
        if gdrive_manager.enabled and (not ws.exists() or not any(ws.iterdir())):
            await gdrive_manager.restore_workspace(project.id, project.workspace_path, project.gdrive_file_id)
    except Exception:
        pass

    return project


async def get_thread(db: AsyncSession, thread_id: str) -> Thread:
    thread = await db.get(Thread, thread_id)
    if thread is None:
        raise NotFound(f"Thread {thread_id} not found")
    return thread


async def get_thread_and_project(db: AsyncSession, thread_id: str) -> tuple[Thread, Project]:
    thread = await get_thread(db, thread_id)
    project = await get_project(db, thread.project_id)
    return thread, project
