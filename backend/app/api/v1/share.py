"""Public read-only share links for threads, plus artifact comments."""

from __future__ import annotations

import secrets

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.api.deps import DB, Auth, get_thread
from app.api.v1.threads import serialize, serialize_message
from app.core.audit import record
from app.core.errors import NotFound
from app.core.utils import iso
from app.db.models import Artifact, ArtifactComment, Message, ShareLink, Thread, ToolCallRecord

router = APIRouter(tags=["share"])


class ShareIn(BaseModel):
    role: str = Field(default="viewer", pattern="^(viewer)$")


def _serialize_share(link: ShareLink) -> dict:
    return {
        "id": link.id,
        "thread_id": link.thread_id,
        "token": link.token,
        "role": link.role,
        "views": link.views,
        "created_at": iso(link.created_at),
    }


@router.get("/threads/{thread_id}/shares")
async def list_shares(thread_id: str, db: DB, _: Auth):
    await get_thread(db, thread_id)
    rows = (await db.execute(select(ShareLink).where(ShareLink.thread_id == thread_id))).scalars().all()
    return [_serialize_share(r) for r in rows]


@router.post("/threads/{thread_id}/share", status_code=201)
async def create_share(thread_id: str, body: ShareIn, db: DB, auth: Auth):
    thread = await get_thread(db, thread_id)
    link = ShareLink(thread_id=thread.id, token=secrets.token_urlsafe(24), role=body.role)
    db.add(link)
    await db.commit()
    await record(db, "share.create", {"thread_id": thread_id}, actor=auth)
    return _serialize_share(link)


@router.delete("/share/{share_token}")
async def revoke_share(share_token: str, db: DB, auth: Auth):
    await db.execute(delete(ShareLink).where(ShareLink.token == share_token))
    await db.commit()
    await record(db, "share.revoke", {"token": share_token[:8] + "…"}, actor=auth)
    return {"revoked": True}


@router.get("/share/{share_token}")
async def view_share(share_token: str, db: DB):
    """Public endpoint — no auth required. Only published thread content."""
    link = (
        await db.execute(select(ShareLink).where(ShareLink.token == share_token))
    ).scalar_one_or_none()
    if link is None:
        raise NotFound("Share link not found or revoked")
    thread = await db.get(Thread, link.thread_id)
    if thread is None:
        raise NotFound("Thread no longer exists")

    messages = (
        await db.execute(
            select(Message).where(Message.thread_id == thread.id).order_by(Message.position)
        )
    ).scalars().all()
    tool_calls = (
        await db.execute(
            select(ToolCallRecord)
            .where(ToolCallRecord.thread_id == thread.id)
            .order_by(ToolCallRecord.created_at)
        )
    ).scalars().all()
    by_message: dict[str, list[ToolCallRecord]] = {}
    for record_ in tool_calls:
        by_message.setdefault(record_.message_id or "", []).append(record_)

    link.views += 1
    await db.commit()
    return {
        "thread": serialize(thread),
        "messages": [
            serialize_message(m, by_message.get(m.id, []))
            for m in messages
            if m.role in ("user", "assistant")
        ],
    }


class CommentIn(BaseModel):
    content: str = Field(min_length=1, max_length=5000)
    author: str = Field(default="you", max_length=120)


@router.get("/threads/{thread_id}/artifacts/{artifact_id}/comments")
async def list_comments(thread_id: str, artifact_id: str, db: DB, _: Auth):
    await get_thread(db, thread_id)
    artifact = await db.get(Artifact, artifact_id)
    if artifact is None or artifact.thread_id != thread_id:
        raise NotFound("Artifact not found")
    rows = (
        await db.execute(
            select(ArtifactComment)
            .where(ArtifactComment.artifact_id == artifact_id)
            .order_by(ArtifactComment.created_at)
        )
    ).scalars().all()
    return [
        {"id": c.id, "author": c.author, "content": c.content, "created_at": iso(c.created_at)}
        for c in rows
    ]


@router.post("/threads/{thread_id}/artifacts/{artifact_id}/comments", status_code=201)
async def add_comment(thread_id: str, artifact_id: str, body: CommentIn, db: DB, auth: Auth):
    await get_thread(db, thread_id)
    artifact = await db.get(Artifact, artifact_id)
    if artifact is None or artifact.thread_id != thread_id:
        raise NotFound("Artifact not found")
    comment = ArtifactComment(artifact_id=artifact_id, author=body.author, content=body.content)
    db.add(comment)
    await db.commit()
    await record(db, "artifact.comment", {"artifact_id": artifact_id}, actor=auth)
    return {"id": comment.id, "author": comment.author, "content": comment.content}
