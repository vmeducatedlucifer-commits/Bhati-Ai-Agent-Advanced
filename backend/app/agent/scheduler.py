"""In-process cron scheduler for agent jobs.

Polls `scheduled_jobs` every minute and runs due prompts through the normal
`AgentRunner` loop in the job's thread. State lives in the database, so jobs
survive restarts; execution requires the server to be running.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.logging import get_logger
from app.db.models import Project, ScheduledJob, Thread
from app.db.session import SessionLocal

log = get_logger("app.scheduler")

POLL_SECONDS = 60


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def _run_job(job_id: str) -> None:
    from app.agent.loop import AgentRunner, runs

    async with SessionLocal() as db:
        job = await db.get(ScheduledJob, job_id)
        if job is None or not job.enabled:
            return
        thread = await db.get(Thread, job.thread_id) if job.thread_id else None
        project = await db.get(Project, job.project_id) if job.project_id else None
        if thread is None or project is None:
            job.enabled = False
            job.last_status = "missing-target"
            await db.commit()
            return
        if runs.is_running(thread.id):
            log.info("skipping job %s: thread %s already running", job.id, thread.id)
            return
        prompt, tid, pid = job.prompt, thread.id, project.id

    try:
        async with SessionLocal() as db:
            thread = await db.get(Thread, tid)
            project = await db.get(Project, pid)
            if thread is None or project is None:
                return
            runner = AgentRunner(thread=thread, project=project)
            await runner.run(f"[Scheduled job] {prompt}")
        status = "ok"
    except Exception as exc:
        log.warning("scheduled job %s failed: %s", job_id, exc)
        status = "error"

    async with SessionLocal() as db:
        job = await db.get(ScheduledJob, job_id)
        if job:
            now = _utcnow()
            job.last_run_at = now
            job.last_status = status
            job.next_run_at = now + timedelta(minutes=max(1, job.interval_minutes or 60))
            await db.commit()


async def _tick() -> None:
    now = _utcnow()
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(ScheduledJob).where(
                    ScheduledJob.enabled.is_(True),
                    (ScheduledJob.next_run_at.is_(None)) | (ScheduledJob.next_run_at <= now),
                )
            )
        ).scalars().all()
        due = [(j.id, j.prompt) for j in rows]
        # Claim them immediately so a second tick can't double-run.
        for job in rows:
            job.next_run_at = now + timedelta(minutes=max(1, job.interval_minutes or 60))
        await db.commit()
    for job_id, _ in due:
        asyncio.create_task(_run_job(job_id))


async def _loop() -> None:
    log.info("scheduler started (poll every %ss)", POLL_SECONDS)
    while True:
        try:
            await _tick()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("scheduler tick failed: %s", exc)
        await asyncio.sleep(POLL_SECONDS)


_task: asyncio.Task | None = None


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())


async def stop() -> None:
    global _task
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
    _task = None
