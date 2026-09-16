"""Advanced features: scheduled jobs, usage stats, snapshots, clone,
storage meter, GitHub push, email transcripts, webhooks, audit trail."""

from __future__ import annotations

import asyncio
import hmac
import os
import re
import shutil
import smtplib
import zipfile
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from app.api.deps import DB, Auth, get_project, get_thread
from app.core.archive import IGNORE_DIRS, build_workspace_zip, slugify_filename
from app.core.audit import record
from app.core.config import settings
from app.core.errors import AppError, NotFound
from app.core.utils import iso, new_id, slugify
from app.db.models import (
    AuditLog,
    Message,
    Project,
    ScheduledJob,
    Thread,
    UsageStat,
)

router = APIRouter(tags=["advanced"])


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------- jobs ---


class JobIn(BaseModel):
    name: str = Field(default="Scheduled run", max_length=200)
    project_id: str
    thread_id: str | None = None
    prompt: str = Field(min_length=1)
    interval_minutes: int = Field(default=60, ge=5, le=10080)


class JobPatch(BaseModel):
    name: str | None = None
    prompt: str | None = None
    interval_minutes: int | None = Field(default=None, ge=5, le=10080)
    enabled: bool | None = None
    thread_id: str | None = None


def _serialize_job(job: ScheduledJob) -> dict:
    return {
        "id": job.id,
        "name": job.name,
        "project_id": job.project_id,
        "thread_id": job.thread_id,
        "prompt": job.prompt,
        "interval_minutes": job.interval_minutes,
        "enabled": job.enabled,
        "next_run_at": iso(job.next_run_at),
        "last_run_at": iso(job.last_run_at),
        "last_status": job.last_status,
    }


@router.get("/jobs")
async def list_jobs(db: DB, _: Auth, project_id: str | None = None):
    query = select(ScheduledJob).order_by(ScheduledJob.next_run_at)
    if project_id:
        query = query.where(ScheduledJob.project_id == project_id)
    rows = (await db.execute(query)).scalars().all()
    return [_serialize_job(j) for j in rows]


@router.post("/jobs", status_code=201)
async def create_job(body: JobIn, db: DB, auth: Auth):
    project = await get_project(db, body.project_id)
    thread_id = body.thread_id
    if thread_id:
        thread = await db.get(Thread, thread_id)
        if thread is None or thread.project_id != project.id:
            raise NotFound("Thread not found in this project")
    else:
        thread = Thread(project_id=project.id, title=body.name, mode="agent", source="scheduler")
        db.add(thread)
        await db.flush()
        thread_id = thread.id
    job = ScheduledJob(
        name=body.name,
        project_id=project.id,
        thread_id=thread_id,
        prompt=body.prompt,
        interval_minutes=body.interval_minutes,
        next_run_at=_utcnow() + timedelta(minutes=body.interval_minutes),
    )
    db.add(job)
    await db.commit()
    await record(db, "job.create", {"job_id": job.id, "project_id": project.id}, actor=auth)
    return _serialize_job(job)


@router.patch("/jobs/{job_id}")
async def patch_job(job_id: str, body: JobPatch, db: DB, _: Auth):
    job = await db.get(ScheduledJob, job_id)
    if job is None:
        raise NotFound("Job not found")
    if body.thread_id is not None:
        thread = await db.get(Thread, body.thread_id)
        if thread is None or thread.project_id != job.project_id:
            raise NotFound("Thread not found in this job's project")
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(job, field, value)
    if body.interval_minutes and job.enabled:
        job.next_run_at = _utcnow() + timedelta(minutes=body.interval_minutes)
    await db.commit()
    return _serialize_job(job)


@router.delete("/jobs/{job_id}")
async def delete_job(job_id: str, db: DB, auth: Auth):
    await db.execute(delete(ScheduledJob).where(ScheduledJob.id == job_id))
    await db.commit()
    await record(db, "job.delete", {"job_id": job_id}, actor=auth)
    return {"deleted": job_id}


@router.post("/jobs/{job_id}/run-now")
async def run_job_now(job_id: str, db: DB, _: Auth):
    job = await db.get(ScheduledJob, job_id)
    if job is None:
        raise NotFound("Job not found")
    from app.agent.scheduler import _run_job

    asyncio.create_task(_run_job(job.id))
    return {"started": job_id}


# --------------------------------------------------------------- stats ---


@router.get("/stats/overview")
async def stats_overview(db: DB, _: Auth):
    totals = await db.execute(
        select(
            func.coalesce(func.sum(UsageStat.prompt_tokens), 0),
            func.coalesce(func.sum(UsageStat.completion_tokens), 0),
            func.count(UsageStat.id),
        )
    )
    prompt_toks, completion_toks, runs = totals.one()
    threads = (await db.execute(select(func.count(Thread.id)))).scalar_one()
    projects = (await db.execute(select(func.count(Project.id)))).scalar_one()
    return {
        "prompt_tokens": int(prompt_toks),
        "completion_tokens": int(completion_toks),
        "total_tokens": int(prompt_toks) + int(completion_toks),
        "runs": int(runs),
        "threads": int(threads),
        "projects": int(projects),
    }


@router.get("/stats/by-model")
async def stats_by_model(db: DB, _: Auth):
    rows = (
        await db.execute(
            select(
                UsageStat.model,
                func.coalesce(func.sum(UsageStat.prompt_tokens), 0),
                func.coalesce(func.sum(UsageStat.completion_tokens), 0),
                func.count(UsageStat.id),
                func.coalesce(func.avg(UsageStat.latency_ms), 0),
            ).group_by(UsageStat.model)
        )
    ).all()
    return [
        {
            "model": model or "unknown",
            "prompt_tokens": int(p),
            "completion_tokens": int(c),
            "total_tokens": int(p) + int(c),
            "runs": int(n),
            "avg_latency_ms": int(avg),
        }
        for model, p, c, n, avg in rows
    ]


@router.get("/stats/daily")
async def stats_daily(db: DB, _: Auth, days: int = 14):
    days = max(1, min(days, 90))
    since = _utcnow() - timedelta(days=days)
    rows = (
        await db.execute(
            select(
                func.date(UsageStat.created_at),
                func.coalesce(func.sum(UsageStat.prompt_tokens), 0),
                func.coalesce(func.sum(UsageStat.completion_tokens), 0),
                func.count(UsageStat.id),
            )
            .where(UsageStat.created_at >= since)
            .group_by(func.date(UsageStat.created_at))
            .order_by(func.date(UsageStat.created_at))
        )
    ).all()
    return [
        {"day": str(day), "prompt_tokens": int(p), "completion_tokens": int(c), "runs": int(n)}
        for day, p, c, n in rows
    ]


# ----------------------------------------------------------- snapshots ---


def _snapshot_dir(project_id: str) -> Path:
    path = Path(settings.DATA_DIR) / "snapshots" / project_id
    path.mkdir(parents=True, exist_ok=True)
    return path


@router.get("/projects/{project_id}/snapshots")
async def list_snapshots(project_id: str, db: DB, _: Auth):
    await get_project(db, project_id)
    out = []
    for file in sorted(_snapshot_dir(project_id).glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True):
        stat = file.stat()
        out.append({"name": file.stem, "size": stat.st_size, "created_at": iso(datetime.fromtimestamp(stat.st_mtime, UTC))})
    return out


class SnapshotIn(BaseModel):
    label: str = Field(default="", max_length=80)


@router.post("/projects/{project_id}/snapshots", status_code=201)
async def create_snapshot(project_id: str, body: SnapshotIn, db: DB, auth: Auth):
    project = await get_project(db, project_id)
    stamp = _utcnow().strftime("%Y%m%d-%H%M%S")
    label = slugify_filename(body.label) if body.label.strip() else "manual"
    tmp = await asyncio.to_thread(build_workspace_zip, Path(project.workspace_path), "")
    dest = _snapshot_dir(project_id) / f"{stamp}-{label}.zip"
    await asyncio.to_thread(shutil.move, str(tmp), str(dest))
    await record(db, "snapshot.create", {"project_id": project_id, "name": dest.stem}, actor=auth)
    return {"name": dest.stem, "size": dest.stat().st_size}


@router.post("/projects/{project_id}/snapshots/{name}/restore")
async def restore_snapshot(project_id: str, name: str, db: DB, auth: Auth):
    project = await get_project(db, project_id)
    snap = _snapshot_dir(project_id) / f"{Path(name).name}.zip"
    if not snap.is_file():
        raise NotFound("Snapshot not found")

    def _restore() -> int:
        from app.core.archive import MAX_BYTES, MAX_FILES

        with zipfile.ZipFile(snap) as zf:
            if zf.testzip() is not None:
                raise AppError("Snapshot archive is corrupt", code="corrupt")
            members = zf.infolist()
            if len(members) > MAX_FILES:
                raise AppError("Snapshot has too many files", code="too_large", status_code=413)
            total = sum(m.file_size for m in members)
            if total > MAX_BYTES:
                raise AppError("Snapshot uncompresses past 500 MB", code="too_large", status_code=413)
            ws = Path(project.workspace_path)
            ws.mkdir(parents=True, exist_ok=True)
            base = ws.resolve()
            for member in members:
                # Zip-slip guard: every member must land strictly inside ws.
                member_name = member.filename.replace("\\", "/")
                if not member_name or member_name.startswith("/") or ".." in member_name.split("/"):
                    raise AppError(f"Snapshot member escapes workspace: {member_name[:80]}", code="bad_archive")
                target = (base / member_name).resolve()
                if target != base and base not in target.parents:
                    raise AppError("Snapshot member escapes workspace", code="bad_archive")
                zf.extract(member, ws)
            return len(members)

    count = await asyncio.to_thread(_restore)
    await record(db, "snapshot.restore", {"project_id": project_id, "name": name}, actor=auth)
    return {"restored": name, "files": count}


@router.delete("/projects/{project_id}/snapshots/{name}")
async def delete_snapshot(project_id: str, name: str, db: DB, _: Auth):
    await get_project(db, project_id)
    snap = _snapshot_dir(project_id) / f"{Path(name).name}.zip"
    if snap.is_file():
        await asyncio.to_thread(snap.unlink)
    return {"deleted": name}


# --------------------------------------------------------- clone/push ---


class CloneIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


def _ignore_for_clone(_dir: str, names: list[str]) -> list[str]:
    return [n for n in names if n in IGNORE_DIRS]


@router.post("/projects/{project_id}/clone", status_code=201)
async def clone_project(project_id: str, body: CloneIn, db: DB, auth: Auth):
    project = await get_project(db, project_id)
    clone_id = new_id("prj")
    slug = slugify(body.name)
    workspace = os.path.join(settings.WORKSPACE_ROOT, f"{slug}-{clone_id[-6:]}")

    def _copy() -> int:
        src = Path(project.workspace_path)
        count = 0
        if src.is_dir():
            shutil.copytree(src, workspace, ignore=_ignore_for_clone)
            count = sum(1 for _ in Path(workspace).rglob("*") if _.is_file())
        else:
            Path(workspace).mkdir(parents=True, exist_ok=True)
        return count

    files = await asyncio.to_thread(_copy)
    clone = Project(
        id=clone_id,
        name=body.name,
        description=f"Cloned from {project.name}",
        instructions=project.instructions,
        icon=project.icon,
        color=project.color,
        slug=slug,
        workspace_path=workspace,
    )
    db.add(clone)
    await db.commit()
    await record(db, "project.clone", {"from": project_id, "to": clone_id}, actor=auth)
    return {"id": clone.id, "name": clone.name, "files_copied": files}


@router.get("/projects/{project_id}/storage")
async def project_storage(project_id: str, db: DB, _: Auth):
    project = await get_project(db, project_id)

    def _walk() -> dict[str, int]:
        total = 0
        count = 0
        root = Path(project.workspace_path)
        if root.is_dir():
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
                for filename in filenames:
                    try:
                        total += (Path(dirpath) / filename).stat().st_size
                        count += 1
                    except OSError:
                        pass
        return {"bytes": total, "files": count}

    return await asyncio.to_thread(_walk)


@router.post("/projects/{project_id}/push")
async def push_project(project_id: str, db: DB, auth: Auth):
    project = await get_project(db, project_id)
    from app.storage.github import github_manager

    if not await github_manager.is_enabled():
        raise AppError("GitHub not connected — add a token in Settings → Connectors", code="no_github")
    repo = await github_manager.sync_workspace(project.id, project.workspace_path, project.github_repo or None)
    if not repo:
        raise AppError("GitHub push failed — check the token and network", code="push_failed")
    await record(db, "project.push", {"project_id": project_id, "repo": repo}, actor=auth)
    return {"repo": repo}


# --------------------------------------------------------------- email ---


class EmailIn(BaseModel):
    to: str = Field(min_length=3, max_length=320)


EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def _clean_subject(text: str) -> str:
    return re.sub(r"[\r\n]+", " ", text or "").strip()[:200]


def _send_email_sync(host: str, port: int, user: str, password: str, sender: str, to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(body)
    with smtplib.SMTP(host, port, timeout=30) as smtp:
        smtp.starttls()
        if user:
            smtp.login(user, password)
        smtp.send_message(msg)


@router.post("/threads/{thread_id}/email-transcript")
async def email_transcript(thread_id: str, body: EmailIn, db: DB, auth: Auth):
    thread = await get_thread(db, thread_id)
    if not settings.SMTP_HOST or not body.to:
        raise AppError("Email not configured — set SMTP_HOST (and credentials) on the backend", code="no_smtp")
    to = body.to.strip()
    if not EMAIL_RE.match(to):
        raise AppError("Invalid recipient address", code="bad_email")
    rows = (
        await db.execute(
            select(Message).where(Message.thread_id == thread_id).order_by(Message.position)
        )
    ).scalars().all()
    transcript = "\n\n".join(
        f"## {m.role.upper()}\n\n{m.content or ''}" for m in rows if m.role in ("user", "assistant")
    )
    sender = settings.SMTP_FROM or settings.SMTP_USER or "bhati-ai-agent@localhost"
    await asyncio.to_thread(
        _send_email_sync,
        settings.SMTP_HOST,
        settings.SMTP_PORT,
        settings.SMTP_USER,
        settings.SMTP_PASS,
        sender,
        to,
        f"[Rawal AI] {_clean_subject(thread.title)}",
        transcript or "(empty conversation)",
    )
    await record(db, "thread.email", {"thread_id": thread_id, "to": to}, actor=auth)
    return {"sent": to}


# ------------------------------------------------------------ webhooks ---


@router.post("/webhooks/github")
async def github_webhook(request: Request, db: DB, project_id: str, token: str = ""):
    """GitHub push webhook → agent run. Configure the hook URL as
    `https://<backend>/api/v1/webhooks/github?project_id=<id>&token=<secret>`."""
    secret = settings.GITHUB_WEBHOOK_SECRET
    if not secret:
        raise AppError("Webhooks are disabled — set GITHUB_WEBHOOK_SECRET", code="forbidden", status_code=403)
    if not hmac.compare_digest(token, secret):
        raise AppError("Invalid webhook token", code="forbidden", status_code=403)
    project = await get_project(db, project_id)
    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        payload = {}
    repo = (payload.get("repository") or {}).get("full_name", "unknown repo")
    commits = payload.get("commits") or []
    summary = "; ".join(c.get("message", "")[:120] for c in commits[:5]) or "push event"
    ref = payload.get("ref", "")

    thread = Thread(
        project_id=project.id,
        title=f"Webhook {ref.split('/')[-1] if ref else 'push'}",
        mode="agent",
        source="webhook",
    )
    db.add(thread)
    await db.commit()

    from app.agent.loop import AgentRunner

    runner = AgentRunner(thread=thread, project=project)
    asyncio.create_task(runner.run(f"[GitHub webhook] {repo} {ref}: {summary}. Pull latest changes if a repo is linked, then review/test as appropriate."))
    return {"accepted": thread.id}


# --------------------------------------------------------------- audit ---


@router.get("/audit")
async def list_audit(db: DB, _: Auth, limit: int = 100):
    limit = max(1, min(limit, 500))
    rows = (
        await db.execute(select(AuditLog).order_by(AuditLog.id.desc()).limit(limit))
    ).scalars().all()
    return [
        {"id": r.id, "actor": r.actor, "action": r.action, "detail": r.detail, "created_at": iso(r.created_at)}
        for r in rows
    ]
