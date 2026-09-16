"""Sandbox lifecycle: one per thread, created on demand, reaped when idle."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.crypto import decrypt
from app.core.logging import get_logger
from app.db.models import Setting
from app.db.session import SessionLocal
from app.sandbox.base import Sandbox, SandboxInfo
from app.sandbox.docker_sandbox import DockerSandbox, docker_available
from app.sandbox.local_sandbox import LocalSandbox
from app.sandbox.superserve import SuperserveClient, SuperservePool, SuperserveSandbox

log = get_logger("app.sandbox.manager")

SANDBOX_CONFIG_KEY = "sandbox_config"


async def load_sandbox_config() -> dict[str, Any]:
    """DB-backed sandbox setting (Settings → Sandbox). Missing → {}."""
    try:
        async with SessionLocal() as db:
            row = await db.get(Setting, SANDBOX_CONFIG_KEY)
            if row and isinstance(row.value, dict):
                return dict(row.value)
    except Exception as exc:
        log.warning("could not load sandbox config: %s", exc)
    return {}


async def save_sandbox_config(patch: dict[str, Any]) -> dict[str, Any]:
    async with SessionLocal() as db:
        row = await db.get(Setting, SANDBOX_CONFIG_KEY)
        current = dict(row.value) if row and isinstance(row.value, dict) else {}
        current.update({k: v for k, v in patch.items() if v is not None})
        if row is None:
            db.add(Setting(key=SANDBOX_CONFIG_KEY, value=current))
        else:
            row.value = current
        await db.commit()
        return current


def resolve_superserve_key(config: dict[str, Any] | None = None) -> str:
    config = config if config is not None else {}
    enc = str(config.get("superserve_key_enc") or "")
    if enc:
        key = decrypt(enc)
        if key:
            return key
    return settings.SUPERSERVE_API_KEY


class SandboxManager:
    def __init__(self) -> None:
        self._boxes: dict[str, Sandbox] = {}
        self._touched: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._backend: str | None = None
        self._reaper: asyncio.Task | None = None
        self._pool: SuperservePool | None = None
        self._pool_client: SuperserveClient | None = None

    # ---- backend selection ----------------------------------------------

    async def backend(self) -> str:
        if self._backend is None:
            config = await load_sandbox_config()
            configured = str(config.get("backend") or settings.SANDBOX_BACKEND)
            if configured not in ("auto", "docker", "local", "superserve", "github"):
                log.warning("unknown sandbox backend %r — using auto", configured)
                configured = "auto"
            if configured == "auto":
                self._backend = "docker" if await asyncio.to_thread(docker_available) else "local"
                if self._backend == "local":
                    log.warning("Docker unavailable — sandboxes will run on the host process")
            elif configured == "superserve":
                if resolve_superserve_key(config):
                    self._backend = "superserve"
                else:
                    log.warning("superserve selected but no API key set — falling back to local")
                    self._backend = "local"
            else:
                self._backend = configured
            log.info("sandbox backend: %s", self._backend)
        return self._backend

    async def configure(self) -> str:
        """Drop cached selection (call after the sandbox setting changes)."""
        self._backend = None
        if self._pool is not None:
            await self._pool.shutdown()
            self._pool = None
            self._pool_client = None
        backend = await self.backend()
        if backend == "superserve":
            await self._ensure_pool()
            pool = self._pool
            if pool is not None:
                asyncio.create_task(pool.maintain(), name="superserve-warmup")
        return backend

    def _lock(self, key: str) -> asyncio.Lock:
        return self._locks.setdefault(key, asyncio.Lock())

    # ---- lifecycle -------------------------------------------------------

    async def get(self, thread_id: str, workspace: str) -> Sandbox:
        async with self._lock(thread_id):
            box = self._boxes.get(thread_id)
            if box is None:
                Path(workspace).mkdir(parents=True, exist_ok=True)
                backend = await self.backend()
                if backend == "docker":
                    box = DockerSandbox(thread_id, workspace)
                    try:
                        await box.start()
                    except Exception as exc:
                        log.warning("docker sandbox failed for %s (%s) — using local", thread_id, exc)
                        box = LocalSandbox(thread_id, workspace)
                        await box.start()
                elif backend == "superserve":
                    box = await self._get_superserve(thread_id, workspace)
                elif backend == "github":
                    box = await self._get_github(thread_id, workspace)
                else:
                    box = LocalSandbox(thread_id, workspace)
                    await box.start()
                self._boxes[thread_id] = box
            self._touched[thread_id] = time.time()
            return box

    async def _get_superserve(self, thread_id: str, workspace: str) -> Sandbox:
        """Lease a warm pooled box (or create one); fall back to local."""
        try:
            pool = await self._ensure_pool()
            config = await load_sandbox_config()
            template = str(config.get("template") or settings.SUPERSERVE_TEMPLATE)
            acquired = await pool.acquire() if pool is not None else None
            if acquired is None:
                raise RuntimeError(pool.last_error if pool else "pool unavailable")
            client = self._pool_client
            assert client is not None
            box = SuperserveSandbox(
                thread_id, workspace, client,
                box_id=acquired.id, access_token=acquired.access_token,
            )
            await box.start()
            log.info("thread %s on superserve box %s (template %s)", thread_id, acquired.id, template)
            return box
        except Exception as exc:
            log.warning("superserve lease failed for %s (%s) — using local", thread_id, exc)
            box = LocalSandbox(thread_id, workspace)
            await box.start()
            return box

    async def _get_github(self, thread_id: str, workspace: str) -> Sandbox:
        """GitHub Actions backend: free cloud runners, minutes per command.

        Best for heavy background jobs on restricted hosts — not interactive
        use. Falls back to local when GitHub is not connected.
        """
        try:
            from app.connectors import get_client as get_connector_client
            from app.db.models import Project, Thread
            from app.sandbox.github_actions import GitHubActionsSandbox

            async with SessionLocal() as db:
                thread = await db.get(Thread, thread_id)
                project = await db.get(Project, thread.project_id) if thread else None
                client = await get_connector_client(db, "github")
                repo = (project.github_repo or "").strip() if project else ""
                slug = (project.slug or "").strip() if project else ""
            if client is None:
                raise RuntimeError("GitHub is not connected")
            if not repo:
                try:
                    me = await client.whoami()
                    login = str(me.get("login") or "").strip()
                except Exception:
                    login = ""
                if not login:
                    raise RuntimeError("GitHub is not connected")
                safe = "".join(
                    c if c.isalnum() or c in "-_" else "-" for c in slug.lower()
                ).strip("-") or thread_id[:8]
                repo = f"{login}/{safe}"
            box = GitHubActionsSandbox(thread_id, workspace, client, repo)
            await box.start()
            log.info("thread %s on github actions repo %s", thread_id, repo)
            return box
        except Exception as exc:
            log.warning("github backend failed for %s (%s) — using local", thread_id, exc)
            box = LocalSandbox(thread_id, workspace)
            await box.start()
            return box

    async def _ensure_pool(self) -> SuperservePool | None:
        config = await load_sandbox_config()
        key = resolve_superserve_key(config)
        if not key:
            return None
        if self._pool is None or self._pool_client is None:
            self._pool_client = SuperserveClient(key)
            try:
                size = int(config.get("pool_size") or settings.SUPERSERVE_POOL_SIZE)
            except (TypeError, ValueError):
                size = settings.SUPERSERVE_POOL_SIZE
            template = str(config.get("template") or settings.SUPERSERVE_TEMPLATE)
            self._pool = SuperservePool(
                client=self._pool_client, size=max(0, min(size, 20)), template=template,
            )
            self._pool.start()
        return self._pool

    async def pool_status(self) -> dict[str, Any]:
        if self._pool is None:
            return {"active": False}
        return {"active": True, **self._pool.status()}

    async def peek(self, thread_id: str) -> Sandbox | None:
        return self._boxes.get(thread_id)

    def touch(self, thread_id: str) -> None:
        """Mark a box recently-used WITHOUT creating it.

        Heartbeats (open UI), agent steps and terminal activity call this so
        the idle reaper only ever collects boxes nobody is watching or using.
        Missing boxes stay missing — this never resurrects anything.
        """
        if thread_id in self._boxes:
            self._touched[thread_id] = time.time()

    async def release(self, thread_id: str, *, remove: bool = True) -> None:
        async with self._lock(thread_id):
            box = self._boxes.pop(thread_id, None)
            self._touched.pop(thread_id, None)
        if box is not None:
            await box.stop(remove=remove)

    async def restart(self, thread_id: str, workspace: str) -> Sandbox:
        await self.release(thread_id)
        return await self.get(thread_id, workspace)

    async def info(self, thread_id: str) -> SandboxInfo | None:
        box = self._boxes.get(thread_id)
        return await box.info() if box else None

    async def list(self) -> list[SandboxInfo]:
        return [await box.info() for box in list(self._boxes.values())]

    # ---- reaper ----------------------------------------------------------

    def start_reaper(self) -> None:
        if self._reaper is None or self._reaper.done():
            self._reaper = asyncio.create_task(self._reap_loop())

    async def _reap_loop(self) -> None:
        interval = max(60, settings.SANDBOX_IDLE_TIMEOUT_S // 4)
        while True:
            try:
                await asyncio.sleep(interval)
                cutoff = time.time() - settings.SANDBOX_IDLE_TIMEOUT_S
                stale = [tid for tid, ts in self._touched.items() if ts < cutoff]
                for tid in stale:
                    log.info("reaping idle sandbox %s", tid)
                    await self.release(tid)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover
                log.warning("sandbox reaper error: %s", exc)

    async def shutdown(self) -> None:
        if self._reaper:
            self._reaper.cancel()
        if self._pool is not None:
            await self._pool.shutdown()
            self._pool = None
            self._pool_client = None
        for tid in list(self._boxes):
            await self.release(tid)


sandboxes = SandboxManager()
