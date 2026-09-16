"""Workspace file browser and editor endpoints, backed by the thread's sandbox."""

from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

from app.api.deps import DB, Auth, get_thread_and_project
from app.core.archive import build_workspace_zip, resolve_inside, slugify_filename
from app.core.errors import AppError, NotFound
from app.sandbox import sandboxes

router = APIRouter(prefix="/threads", tags=["files"])

TEXT_SUFFIXES = {
    ".txt", ".md", ".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".yaml", ".yml", ".toml",
    ".html", ".css", ".scss", ".sh", ".env", ".sql", ".go", ".rs", ".java", ".rb", ".php",
    ".c", ".h", ".cpp", ".xml", ".ini", ".cfg", ".conf", ".lock", ".gitignore", ".dockerfile",
}


class WriteBody(BaseModel):
    path: str
    content: str


async def _sandbox(db, thread_id: str):
    thread, project = await get_thread_and_project(db, thread_id)
    return await sandboxes.get(thread.id, project.workspace_path), project


@router.get("/{thread_id}/files")
async def list_files(thread_id: str, db: DB, _: Auth, path: str = ""):
    sandbox, _project = await _sandbox(db, thread_id)
    entries = await sandbox.list_dir(path)
    return {
        "path": path,
        "entries": [
            {"name": e.name, "path": e.path, "is_dir": e.is_dir, "size": e.size, "modified": e.modified}
            for e in entries
        ],
    }


@router.get("/{thread_id}/files/content")
async def read_file(thread_id: str, path: str, db: DB, _: Auth):
    sandbox, _project = await _sandbox(db, thread_id)
    suffix = Path(path).suffix.lower()
    if suffix and suffix not in TEXT_SUFFIXES and suffix not in ("",):
        # Still try; binary files come back as replacement characters rather than a 500.
        pass
    try:
        content = await sandbox.read_file(path)
    except Exception as exc:
        raise NotFound(str(exc)) from exc
    return {"path": path, "content": content, "size": len(content.encode())}


@router.put("/{thread_id}/files/content")
async def write_file(thread_id: str, body: WriteBody, db: DB, _: Auth):
    sandbox, _project = await _sandbox(db, thread_id)
    size = await sandbox.write_file(body.path, body.content)
    return {"path": body.path, "size": size}


@router.delete("/{thread_id}/files")
async def delete_file(thread_id: str, path: str, db: DB, _: Auth):
    sandbox, _project = await _sandbox(db, thread_id)
    await sandbox.delete(path)
    return {"deleted": path}


@router.post("/{thread_id}/files/upload")
async def upload(thread_id: str, db: DB, _: Auth, file: UploadFile, path: str = ""):
    _sandbox_obj, project = await _sandbox(db, thread_id)
    target_dir = resolve_inside(Path(project.workspace_path), path or "uploads")
    target_dir.mkdir(parents=True, exist_ok=True)
    name = Path(file.filename or "upload.bin").name or "upload.bin"
    destination = target_dir / name
    # Stream with a cap instead of buffering an unbounded upload in RAM.
    MAX_UPLOAD_BYTES = 100 * 1024 * 1024
    size = 0
    with open(destination, "wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                out.close()
                destination.unlink(missing_ok=True)
                raise AppError("Upload exceeds 100 MB", code="too_large", status_code=413)
            out.write(chunk)
    relative = str(destination.relative_to(Path(project.workspace_path).resolve()))
    return {"path": relative, "size": size, "name": name}


@router.get("/{thread_id}/files/download")
async def download(thread_id: str, path: str, db: DB, _: Auth):
    _sandbox_obj, project = await _sandbox(db, thread_id)
    target = resolve_inside(Path(project.workspace_path), path)
    if not target.is_file():
        raise NotFound(f"{path} is not a file")
    return FileResponse(target, filename=target.name)


@router.get("/{thread_id}/archive")
async def download_archive(thread_id: str, db: DB, _: Auth, path: str = ""):
    """Download a workspace file or folder as a ZIP archive.

    `path` empty → whole thread workspace. Dependency/build directories
    (node_modules, .git, dist, …) are skipped automatically.
    """
    _, project = await _sandbox(db, thread_id)
    root = Path(project.workspace_path)
    try:
        target = await asyncio.to_thread(resolve_inside, root, path)
    except AppError:
        raise
    if not target.exists():
        raise NotFound(f"{path or '.'} not found")

    tmp = await asyncio.to_thread(build_workspace_zip, root, path)
    label = slugify_filename(target.name if path else project.name or project.id)
    filename = f"{label}.zip"
    cleanup = BackgroundTask(lambda: tmp.unlink(missing_ok=True))
    return FileResponse(tmp, media_type="application/zip", filename=filename, background=cleanup)
