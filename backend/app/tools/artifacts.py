"""Artifacts: files the agent hands to the user, and durable project memory."""

from __future__ import annotations

from sqlalchemy import select

from app.core.utils import new_id
from app.db.models import Artifact, Memory
from app.db.session import SessionLocal
from app.tools.base import ToolContext, ToolResult, obj, string
from app.tools.registry import registry


@registry.tool(
    "create_artifact",
    (
        "Publish a deliverable for the user: a report, a chart, an HTML page, a dataset. "
        "It appears in the Artifacts panel with a preview and a download link. Use this for "
        "finished output, not for scratch files."
    ),
    obj(
        {
            "title": string("Human-readable title"),
            "kind": string("Artifact type", enum=["markdown", "html", "code", "file", "image"]),
            "content": string("Full artifact content (for image, a workspace path)"),
            "path": string("Also write it to this workspace path", default=""),
        },
        ["title", "kind", "content"],
    ),
    permission="write",
    group="output",
    mutating=True,
)
async def create_artifact(ctx: ToolContext, title: str, kind: str, content: str, path: str = ""):
    if path:
        await ctx.sandbox.write_file(path, content)

    artifact_id = new_id("art")
    async with SessionLocal() as db:
        db.add(
            Artifact(
                id=artifact_id,
                thread_id=ctx.thread_id,
                title=title,
                kind=kind,
                path=path,
                content=content if kind != "image" else "",
                size=len(content.encode()),
            )
        )
        await db.commit()

    await ctx.emit(
        "artifact",
        {"id": artifact_id, "title": title, "kind": kind, "path": path, "size": len(content)},
    )
    return ToolResult(
        content=f"Published artifact “{title}” ({kind}){f' → {path}' if path else ''}",
        display={"kind": "artifact", "id": artifact_id, "title": title, "artifact_kind": kind, "content": content},
    )


@registry.tool(
    "db_remember",
    (
        "Save a durable fact about this project so future conversations start informed: "
        "conventions, architecture decisions, credentials layout, commands that work. "
        "Overwrite an existing key to correct it. Stored in the project database."
    ),
    obj(
        {
            "key": string("Short stable key, e.g. 'test-command' or 'deploy-flow'"),
            "value": string("The fact, written so a future session can act on it"),
        },
        ["key", "value"],
    ),
    permission="write",
    group="memory",
    mutating=True,
)
async def db_remember(ctx: ToolContext, key: str, value: str):
    async with SessionLocal() as db:
        row = (
            await db.execute(
                select(Memory).where(Memory.project_id == ctx.project_id, Memory.key == key)
            )
        ).scalar_one_or_none()
        if row:
            row.value = value
        else:
            db.add(Memory(project_id=ctx.project_id, key=key, value=value))
        await db.commit()
    await ctx.emit("memory", {"key": key, "value": value})
    return ToolResult(content=f"Remembered `{key}`.")


@registry.tool(
    "db_recall",
    "Look up what you previously remembered about this project in the database. Omit `key` to list everything.",
    obj({"key": string("Specific key to look up", default="")}),
    group="memory",
)
async def db_recall(ctx: ToolContext, key: str = ""):
    async with SessionLocal() as db:
        query = select(Memory).where(Memory.project_id == ctx.project_id)
        if key:
            query = query.where(Memory.key == key)
        rows = (await db.execute(query)).scalars().all()
    if not rows:
        return ToolResult(content="Nothing remembered for this project yet.")
    return ToolResult(content="\n\n".join(f"## {r.key}\n{r.value}" for r in rows))
