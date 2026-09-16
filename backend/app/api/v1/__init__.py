"""API v1 router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    advanced,
    agents,
    auth,
    browser,
    chat,
    files,
    integrations,
    preview,
    projects,
    providers,
    share,
    skills,
    system,
    terminal,
    threads,
)

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(threads.router)
api_router.include_router(chat.router)
api_router.include_router(files.router)
api_router.include_router(terminal.router)
api_router.include_router(providers.router)
api_router.include_router(integrations.router)
api_router.include_router(preview.router)
api_router.include_router(share.router)
api_router.include_router(skills.router)
api_router.include_router(advanced.router)
api_router.include_router(browser.router)
api_router.include_router(agents.router)

__all__ = ["api_router"]
