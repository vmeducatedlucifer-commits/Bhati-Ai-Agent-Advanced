"""Threads: chat sessions inside a project."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.api.deps import DB, Auth, get_project, get_thread
from app.core.audit import record
from app.core.errors import NotFound
from app.core.utils import iso, new_id
from app.db.models import Artifact, Message, Thread, ToolCallRecord
from app.sandbox import sandboxes

router = APIRouter(prefix="/threads", tags=["threads"])


class ThreadIn(BaseModel):
    project_id: str
    title: str = "New chat"
    model: str = ""
    provider_id: str | None = None
    mode: str = Field(default="agent", pattern="^(agent|chat|plan)$")
    permission_mode: str = Field(default="auto", pattern="^(auto|ask|plan)$")
    system_prompt: str = ""


class ThreadPatch(BaseModel):
    title: str | None = None
    model: str | None = None
    provider_id: str | None = None
    mode: str | None = Field(default=None, pattern="^(agent|chat|plan)$")
    permission_mode: str | None = Field(default=None, pattern="^(auto|ask|plan)$")
    system_prompt: str | None = None
    pinned: bool | None = None
    archived: bool | None = None


def serialize(thread: Thread) -> dict:
    return {
        "id": thread.id,
        "project_id": thread.project_id,
        "title": thread.title,
        "model": thread.model,
        "provider_id": thread.provider_id,
        "mode": thread.mode,
        "permission_mode": thread.permission_mode,
        "system_prompt": thread.system_prompt,
        "status": thread.status,
        "pinned": thread.pinned,
        "archived": thread.archived,
        "source": getattr(thread, "source", "web"),
        "todos": thread.todos or [],
        "token_usage": thread.token_usage or {},
        "created_at": iso(thread.created_at),
        "updated_at": iso(thread.updated_at),
        "last_message_at": iso(thread.last_message_at),
    }


def serialize_message(message: Message, tool_calls: list[ToolCallRecord]) -> dict:
    return {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "reasoning": message.reasoning,
        "attachments": message.attachments or [],
        "meta": message.meta or {},
        "error": message.error,
        "created_at": iso(message.created_at),
        "tool_calls": [
            {
                "id": t.call_id,
                "name": t.name,
                "arguments": t.arguments,
                "result": t.result,
                "display": t.display,
                "status": t.status,
                "duration_ms": t.duration_ms,
            }
            for t in tool_calls
        ],
    }


@router.get("")
async def list_threads(db: DB, _: Auth, project_id: str | None = None, limit: int = 100):
    query = select(Thread).where(Thread.archived.is_(False)).order_by(
        Thread.pinned.desc(), Thread.updated_at.desc()
    ).limit(limit)
    if project_id:
        query = query.where(Thread.project_id == project_id)
    return [serialize(t) for t in (await db.execute(query)).scalars().all()]


@router.post("", status_code=201)
async def create_thread(body: ThreadIn, db: DB, _: Auth):
    await get_project(db, body.project_id)
    thread = Thread(**body.model_dump())
    db.add(thread)
    await db.commit()
    return serialize(thread)


@router.get("/{thread_id}")
async def get_one(thread_id: str, db: DB, _: Auth):
    thread = await get_thread(db, thread_id)
    return serialize(thread)


@router.patch("/{thread_id}")
async def patch_thread(thread_id: str, body: ThreadPatch, db: DB, _: Auth):
    thread = await get_thread(db, thread_id)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(thread, field, value)
    await db.commit()
    return serialize(thread)


@router.delete("/{thread_id}")
async def delete_thread(thread_id: str, db: DB, auth: Auth):
    thread = await get_thread(db, thread_id)
    await sandboxes.release(thread_id)
    await db.delete(thread)
    await db.commit()
    await record(db, "thread.delete", {"thread_id": thread_id}, actor=auth)
    return {"deleted": thread_id}


class TruncateIn(BaseModel):
    from_message_id: str


@router.post("/{thread_id}/truncate")
async def truncate_messages(thread_id: str, body: TruncateIn, db: DB, auth: Auth):
    """Delete a message and everything after it (powers edit-resend / regenerate)."""
    thread = await get_thread(db, thread_id)
    anchor = await db.get(Message, body.from_message_id)
    if anchor is None or anchor.thread_id != thread.id:
        raise NotFound("Message not found in this thread")
    await db.execute(
        delete(ToolCallRecord).where(
            ToolCallRecord.thread_id == thread_id,
            ToolCallRecord.message_id.in_(
                select(Message.id).where(
                    Message.thread_id == thread_id, Message.position >= anchor.position
                )
            ),
        )
    )
    await db.execute(
        delete(Message).where(Message.thread_id == thread_id, Message.position >= anchor.position)
    )
    await db.commit()
    await record(db, "thread.truncate", {"thread_id": thread_id}, actor=auth)
    return {"truncated_from": body.from_message_id}


class ForkIn(BaseModel):
    from_message_id: str | None = None
    title: str | None = Field(default=None, max_length=200)


@router.post("/{thread_id}/fork", status_code=201)
async def fork_thread(thread_id: str, body: ForkIn, db: DB, auth: Auth):
    """Branch a new chat copying history up to (and including) a message."""
    thread = await get_thread(db, thread_id)
    query = select(Message).where(Message.thread_id == thread_id).order_by(Message.position)
    if body.from_message_id:
        anchor = await db.get(Message, body.from_message_id)
        if anchor is None or anchor.thread_id != thread_id:
            raise NotFound("Message not found in this thread")
        query = query.where(Message.position <= anchor.position)
    messages = (await db.execute(query)).scalars().all()

    fork = Thread(
        id=new_id("thr"),
        project_id=thread.project_id,
        title=body.title or f"{thread.title} (branch)",
        model=thread.model,
        provider_id=thread.provider_id,
        mode=thread.mode,
        permission_mode=thread.permission_mode,
        system_prompt=thread.system_prompt,
        source=thread.source,
    )
    db.add(fork)
    await db.flush()
    for msg in messages:
        db.add(
            Message(
                id=new_id("msg"),
                thread_id=fork.id,
                position=msg.position,
                role=msg.role,
                content=msg.content,
                reasoning=msg.reasoning,
                raw=msg.raw,
                attachments=msg.attachments,
                meta=msg.meta,
                error=msg.error,
                finished=msg.finished,
            )
        )
    await db.commit()
    await record(db, "thread.fork", {"from": thread_id, "to": fork.id}, actor=auth)
    return serialize(fork)


@router.get("/{thread_id}/messages")
async def list_messages(thread_id: str, db: DB, _: Auth):
    await get_thread(db, thread_id)
    messages = (
        await db.execute(select(Message).where(Message.thread_id == thread_id).order_by(Message.position))
    ).scalars().all()
    tool_calls = (
        await db.execute(
            select(ToolCallRecord)
            .where(ToolCallRecord.thread_id == thread_id)
            .order_by(ToolCallRecord.created_at)
        )
    ).scalars().all()

    by_message: dict[str, list[ToolCallRecord]] = {}
    for entry in tool_calls:
        by_message.setdefault(entry.message_id or "", []).append(entry)

    return [
        serialize_message(m, by_message.get(m.id, []))
        for m in messages
        if m.role in ("user", "assistant")
    ]


@router.delete("/{thread_id}/messages")
async def clear_messages(thread_id: str, db: DB, _: Auth):
    thread = await get_thread(db, thread_id)
    for message in list(thread.messages):
        await db.delete(message)
    thread.todos = []
    await db.commit()
    return {"cleared": thread_id}


@router.get("/{thread_id}/artifacts")
async def list_artifacts(thread_id: str, db: DB, _: Auth):
    rows = (
        await db.execute(
            select(Artifact).where(Artifact.thread_id == thread_id).order_by(Artifact.created_at.desc())
        )
    ).scalars().all()
    return [
        {
            "id": a.id,
            "title": a.title,
            "kind": a.kind,
            "path": a.path,
            "content": a.content,
            "size": a.size,
            "created_at": iso(a.created_at),
        }
        for a in rows
    ]
