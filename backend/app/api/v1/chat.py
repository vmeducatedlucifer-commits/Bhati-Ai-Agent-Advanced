"""Chat: start a run, follow it over SSE, interrupt it, answer permission prompts."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.loop import AgentRunner, runs
from app.agent.permissions import permissions
from app.api.deps import DB, Auth, get_thread_and_project
from app.core.errors import Conflict
from app.core.events import bus
from app.core.logging import get_logger

log = get_logger("app.api.chat")
router = APIRouter(prefix="/threads", tags=["chat"])

HEARTBEAT_SECONDS = 8


class SendBody(BaseModel):
    content: str = Field(min_length=1)
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class SteerBody(BaseModel):
    content: str = Field(min_length=1)


class PermissionBody(BaseModel):
    request_id: str
    decision: str = Field(pattern="^(allow|deny|allow_always)$")


@router.post("/{thread_id}/messages")
async def send_message(thread_id: str, body: SendBody, db: DB, _: Auth):
    """Queue a user turn. Returns immediately; follow `/stream` for the response."""
    thread, project = await get_thread_and_project(db, thread_id)

    # Reserve synchronously before scheduling the task. Checking first and
    # reserving inside AgentRunner leaves a race where two turns can both pass
    # the check and mutate the same conversation concurrently.
    if not runs.reserve(thread_id):
        # A message sent while the agent works becomes a mid-run steer.
        if runs.steer(thread_id, body.content):
            return {"status": "steered", "thread_id": thread_id}
        raise Conflict("A run is already in progress on this thread")

    runner = AgentRunner(thread=thread, project=project)
    asyncio.create_task(runner.run(body.content, body.attachments))
    return {"status": "started", "thread_id": thread_id}


@router.post("/{thread_id}/interrupt")
async def interrupt(thread_id: str, _: Auth):
    stopped = runs.cancel(thread_id)
    return {"interrupted": stopped}


@router.post("/{thread_id}/steer")
async def steer(thread_id: str, body: SteerBody, _: Auth):
    accepted = runs.steer(thread_id, body.content)
    return {"accepted": accepted}


@router.post("/{thread_id}/permissions")
async def decide_permission(thread_id: str, body: PermissionBody, _: Auth):
    resolved = permissions.resolve(thread_id, body.request_id, body.decision)  # type: ignore[arg-type]
    return {"resolved": resolved}


@router.get("/{thread_id}/permissions")
async def pending_permissions(thread_id: str, _: Auth):
    return {"pending": permissions.pending(thread_id)}


@router.get("/{thread_id}/status")
async def run_status(thread_id: str, db: DB, _: Auth):
    thread, _project = await get_thread_and_project(db, thread_id)
    running = runs.is_running(thread_id)
    # In-memory run state disappears on process restart. Repair the persisted
    # status so the UI never shows an immortal spinner after a deploy/crash.
    if not running and thread.status == "running":
        thread.status = "idle"
        await db.commit()
    return {
        "running": running,
        "pending_permissions": permissions.pending(thread_id),
        "subscribers": bus.subscriber_count(f"thread:{thread_id}"),
    }


def _sse(event: dict[str, Any]) -> str:
    return f"id: {event.get('seq', 0)}\nevent: {event.get('type', 'message')}\ndata: {json.dumps(event, default=str)}\n\n"


@router.get("/{thread_id}/stream")
async def stream(thread_id: str, request: Request, _: Auth, after: int = 0):
    """Server-sent events for one thread. Reconnect with `after` to resume without gaps."""
    topic = f"thread:{thread_id}"

    async def generator() -> AsyncIterator[str]:
        yield ": connected\n\n"
        queue: asyncio.Queue = asyncio.Queue()

        async def pump():
            try:
                async for event in bus.subscribe(topic, after_seq=after):
                    await queue.put(event)
            except asyncio.CancelledError:
                raise

        task = asyncio.create_task(pump())
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield ": ping\n\n"
                    continue
                yield _sse(event)
        finally:
            task.cancel()

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
