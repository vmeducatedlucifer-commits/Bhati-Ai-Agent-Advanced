"""Projects: a named workspace directory plus its threads."""

from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from starlette.background import BackgroundTask

from app.api.deps import DB, Auth, get_project
from app.core.archive import build_workspace_zip, slugify_filename
from app.core.audit import record
from app.core.config import settings
from app.core.errors import NotFound
from app.core.utils import iso, new_id, slugify
from app.db.models import Memory, Project, Thread

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    instructions: str = ""
    icon: str = "folder"
    color: str = "orange"


class ProjectPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    instructions: str | None = None
    icon: str | None = None
    color: str | None = None
    archived: bool | None = None


def serialize(project: Project, thread_count: int = 0) -> dict:
    rel_ws = os.path.basename(project.workspace_path) if project.workspace_path else project.slug
    return {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "slug": project.slug,
        "instructions": project.instructions,
        "icon": project.icon,
        "color": project.color,
        "archived": project.archived,
        "workspace_path": f"workspaces/{rel_ws}",
        "thread_count": thread_count,
        "created_at": iso(project.created_at),
        "updated_at": iso(project.updated_at),
    }


@router.get("")
async def list_projects(db: DB, _: Auth, include_archived: bool = False):
    query = select(Project).order_by(Project.updated_at.desc())
    if not include_archived:
        query = query.where(Project.archived.is_(False))
    projects = (await db.execute(query)).scalars().all()

    counts = dict(
        (await db.execute(select(Thread.project_id, func.count(Thread.id)).group_by(Thread.project_id))).all()
    )
    return [serialize(p, counts.get(p.id, 0)) for p in projects]


@router.post("", status_code=201)
async def create_project(body: ProjectIn, db: DB, _: Auth):
    project_id = new_id("prj")
    slug = slugify(body.name)
    workspace = os.path.join(settings.WORKSPACE_ROOT, f"{slug}-{project_id[-6:]}")
    os.makedirs(workspace, exist_ok=True)

    project = Project(
        id=project_id,
        name=body.name,
        description=body.description,
        instructions=body.instructions,
        icon=body.icon,
        color=body.color,
        slug=slug,
        workspace_path=workspace,
    )
    db.add(project)
    await db.commit()
    return serialize(project)


@router.get("/{project_id}")
async def get_one(project_id: str, db: DB, _: Auth):
    project = await get_project(db, project_id)
    count = (
        await db.execute(select(func.count(Thread.id)).where(Thread.project_id == project_id))
    ).scalar_one()
    return serialize(project, int(count))


@router.patch("/{project_id}")
async def patch_project(project_id: str, body: ProjectPatch, db: DB, _: Auth):
    project = await get_project(db, project_id)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(project, field, value)
    await db.commit()
    return serialize(project)


@router.delete("/{project_id}")
async def delete_project(project_id: str, db: DB, auth: Auth, delete_files: bool = True):
    project = await get_project(db, project_id)
    path = project.workspace_path

    from app.sandbox import sandboxes

    thread_ids = (
        await db.execute(select(Thread.id).where(Thread.project_id == project_id))
    ).scalars().all()
    for thread_id in thread_ids:
        await sandboxes.release(thread_id)

    await db.delete(project)
    await db.commit()
    if delete_files and os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
    await record(db, "project.delete", {"project_id": project_id}, actor=auth)
    return {"deleted": project_id}


@router.get("/{project_id}/archive")
async def download_project_archive(project_id: str, db: DB, _: Auth):
    """Download the entire project workspace as a ZIP archive.

    Dependency/build directories are skipped automatically (see
    `app.core.archive.IGNORE_DIRS`). Sandbox containers are untouched —
    the archive is built straight from the host workspace directory.
    """
    project = await get_project(db, project_id)
    root = Path(project.workspace_path)
    if not root.is_dir():
        raise NotFound("Project workspace is empty or missing")

    tmp = await asyncio.to_thread(build_workspace_zip, root, "")
    filename = f"{slugify_filename(project.name or project.id)}.zip"
    cleanup = BackgroundTask(lambda: tmp.unlink(missing_ok=True))
    return FileResponse(tmp, media_type="application/zip", filename=filename, background=cleanup)


@router.get("/{project_id}/memories")
async def list_memories(project_id: str, db: DB, _: Auth):
    await get_project(db, project_id)
    rows = (await db.execute(select(Memory).where(Memory.project_id == project_id))).scalars().all()
    return [{"id": r.id, "key": r.key, "value": r.value, "updated_at": iso(r.updated_at)} for r in rows]


@router.delete("/{project_id}/memories/{memory_id}")
async def delete_memory(project_id: str, memory_id: str, db: DB, _: Auth):
    await db.execute(delete(Memory).where(Memory.id == memory_id, Memory.project_id == project_id))
    await db.commit()
    return {"deleted": memory_id}
