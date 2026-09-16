"""Per-thread Docker container: the real Manus-style isolated machine.

One container per chat thread. The project workspace is bind-mounted at /workspace so
files survive container restarts, and the agent gets a throwaway Linux box with its own
process table, package manager, and network namespace.

The docker SDK is synchronous, so every call is pushed onto a worker thread.
"""

from __future__ import annotations

import asyncio
import io
import shlex
import tarfile
import time
from collections.abc import AsyncIterator
from typing import Any

from app.core.config import settings
from app.core.errors import SandboxError
from app.core.logging import get_logger
from app.sandbox.base import ExecResult, FileEntry, Sandbox, SandboxInfo

log = get_logger("app.sandbox.docker")

CONTAINER_WORKDIR = "/workspace"
LABEL_KEY = "com.bhati.agent"

_BOOTSTRAP = r"""
set -e
export DEBIAN_FRONTEND=noninteractive
if ! command -v git >/dev/null 2>&1; then
  (apt-get update -qq && apt-get install -y -qq --no-install-recommends \
     git curl ca-certificates ripgrep procps unzip >/dev/null 2>&1) || true
fi
mkdir -p /workspace
"""


def _docker_client():
    try:
        import docker  # imported lazily so the app still boots without the SDK
    except ImportError as exc:  # pragma: no cover
        raise SandboxError(f"docker SDK not installed: {exc}") from exc
    try:
        client = docker.from_env()
        client.ping()
        return client
    except Exception as exc:
        raise SandboxError(f"Docker daemon unreachable: {exc}") from exc


def docker_available() -> bool:
    try:
        _docker_client()
        return True
    except Exception:
        return False


class DockerSandbox(Sandbox):
    backend = "docker"

    def __init__(self, sandbox_id: str, workspace: str, *, image: str | None = None):
        self.id = sandbox_id
        self.host_workspace = workspace
        self.workdir = CONTAINER_WORKDIR
        self.image = image or settings.SANDBOX_IMAGE
        self.container_name = f"bhati-{sandbox_id}"
        self._container: Any = None
        self._client: Any = None
        self._started_at = 0.0
        self._lock = asyncio.Lock()

    # ---- lifecycle -------------------------------------------------------

    async def start(self) -> SandboxInfo:
        async with self._lock:
            if self._container is not None:
                return await self.info()
            self._client = await asyncio.to_thread(_docker_client)
            self._container = await asyncio.to_thread(self._start_sync)
            self._started_at = time.time()
        # Best-effort tooling install; never block the first command on it.
        asyncio.create_task(self._bootstrap())
        return await self.info()

    def _start_sync(self):
        import docker
        from docker.errors import ImageNotFound, NotFound

        client = self._client

        try:
            existing = client.containers.get(self.container_name)
            if existing.status != "running":
                existing.start()
            return existing
        except NotFound:
            pass

        image = self.image
        try:
            client.images.get(image)
        except ImageNotFound:
            log.info("pulling sandbox image %s", image)
            try:
                client.images.pull(image)
            except Exception:
                log.warning("image %s unavailable, falling back to %s", image, settings.SANDBOX_FALLBACK_IMAGE)
                image = settings.SANDBOX_FALLBACK_IMAGE
                try:
                    client.images.get(image)
                except ImageNotFound:
                    client.images.pull(image)
        self.image = image

        try:
            return client.containers.run(
                image,
                command=["sleep", "infinity"],
                name=self.container_name,
                detach=True,
                working_dir=CONTAINER_WORKDIR,
                volumes={self.host_workspace: {"bind": CONTAINER_WORKDIR, "mode": "rw"}},
                labels={LABEL_KEY: self.id},
                network_mode=settings.SANDBOX_NETWORK,
                mem_limit=f"{settings.SANDBOX_MEMORY_MB}m",
                nano_cpus=int(settings.SANDBOX_CPUS * 1_000_000_000),
                pids_limit=512,
                environment={
                    "HOME": "/root",
                    "TERM": "xterm-256color",
                    "PYTHONUNBUFFERED": "1",
                    "DEBIAN_FRONTEND": "noninteractive",
                },
                tty=False,
                auto_remove=False,
            )
        except docker.errors.APIError as exc:
            raise SandboxError(f"Could not start sandbox container: {exc}") from exc

    async def _bootstrap(self) -> None:
        try:
            await self.exec(_BOOTSTRAP, timeout=240)
        except Exception as exc:  # pragma: no cover
            log.warning("sandbox bootstrap failed for %s: %s", self.id, exc)

    async def stop(self, *, remove: bool = True) -> None:
        async with self._lock:
            container = self._container
            self._container = None
            self._started_at = 0.0
        if container is None:
            return

        def _stop():
            try:
                container.stop(timeout=5)
                if remove:
                    container.remove(force=True)
            except Exception as exc:  # pragma: no cover
                log.warning("stopping sandbox %s failed: %s", self.id, exc)

        await asyncio.to_thread(_stop)

    async def info(self) -> SandboxInfo:
        status = "stopped"
        detail: dict[str, Any] = {"isolated": True, "container": self.container_name}
        if self._container is not None:
            def _reload():
                try:
                    self._container.reload()
                    return self._container.status
                except Exception:
                    return "unknown"

            status = await asyncio.to_thread(_reload)
        return SandboxInfo(
            id=self.id,
            backend=self.backend,
            status=status,
            workspace=CONTAINER_WORKDIR,
            image=self.image,
            started_at=self._started_at,
            detail=detail,
        )

    # ---- exec ------------------------------------------------------------

    def _require(self):
        if self._container is None:
            raise SandboxError("Sandbox is not running")
        return self._container

    @staticmethod
    def _wrap(command: str, cwd: str | None) -> list[str]:
        target = CONTAINER_WORKDIR if not cwd else f"{CONTAINER_WORKDIR}/{cwd.strip('/')}"
        return ["/bin/sh", "-lc", f"cd {shlex.quote(target)} && {command}"]

    async def exec(
        self,
        command: str,
        *,
        cwd: str | None = None,
        timeout: int | None = None,
        env: dict[str, str] | None = None,
    ) -> ExecResult:
        container = self._require()
        timeout = timeout or settings.SANDBOX_COMMAND_TIMEOUT_S
        started = time.perf_counter()

        def _run():
            return container.exec_run(
                self._wrap(command, cwd),
                environment=env or {},
                demux=True,
                workdir=CONTAINER_WORKDIR,
            )

        try:
            res = await asyncio.wait_for(asyncio.to_thread(_run), timeout=timeout)
        except TimeoutError:
            return ExecResult(
                exit_code=124,
                stdout="",
                stderr=f"Command timed out after {timeout}s",
                duration_ms=int((time.perf_counter() - started) * 1000),
                timed_out=True,
            )
        out, err = res.output if isinstance(res.output, tuple) else (res.output, b"")
        return ExecResult(
            exit_code=res.exit_code or 0,
            stdout=(out or b"").decode(errors="replace"),
            stderr=(err or b"").decode(errors="replace"),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    async def exec_stream(
        self,
        command: str,
        *,
        cwd: str | None = None,
        timeout: int | None = None,
        env: dict[str, str] | None = None,
    ) -> AsyncIterator[str]:
        container = self._require()
        timeout = timeout or settings.SANDBOX_COMMAND_TIMEOUT_S
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        loop = asyncio.get_running_loop()

        def _pump():
            try:
                _, stream = container.exec_run(
                    self._wrap(command, cwd),
                    environment=env or {},
                    stream=True,
                    demux=False,
                    workdir=CONTAINER_WORKDIR,
                )
                for chunk in stream:
                    loop.call_soon_threadsafe(queue.put_nowait, chunk.decode(errors="replace"))
            except Exception as exc:  # pragma: no cover
                loop.call_soon_threadsafe(queue.put_nowait, f"\n[sandbox error] {exc}\n")
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        task = asyncio.create_task(asyncio.to_thread(_pump))
        deadline = time.time() + timeout
        try:
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    yield f"\n[timed out after {timeout}s]\n"
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=remaining)
                except TimeoutError:
                    yield f"\n[timed out after {timeout}s]\n"
                    break
                if item is None:
                    break
                yield item
        finally:
            task.cancel()

    # ---- files -----------------------------------------------------------

    @staticmethod
    def _sanitize_path(path: str) -> str:
        """Prevent path traversal escapes inside container workdir."""
        import posixpath
        normalized = posixpath.normpath(posixpath.join(CONTAINER_WORKDIR, path.lstrip("/")))
        if not (normalized == CONTAINER_WORKDIR or normalized.startswith(CONTAINER_WORKDIR + "/")):
            raise SandboxError(f"Path escapes container workspace: {path}")
        return normalized

    async def read_file(self, path: str, *, max_bytes: int = 2_000_000) -> str:
        container = self._require()
        full = self._sanitize_path(path)

        def _get() -> bytes:
            stream, _ = container.get_archive(full)
            buf = io.BytesIO(b"".join(stream))
            with tarfile.open(fileobj=buf) as tar:
                try:
                    member = next(iter(tar), None)
                except StopIteration:
                    member = None
                if member is None or not member.isfile():
                    raise SandboxError(f"Not a file: {path}")
                fh = tar.extractfile(member)
                return fh.read(max_bytes) if fh else b""

        try:
            data = await asyncio.to_thread(_get)
        except SandboxError:
            raise
        except Exception as exc:
            raise SandboxError(f"Could not read {path}: {exc}") from exc
        return data.decode("utf-8", errors="replace")

    async def write_file(self, path: str, content: str) -> int:
        container = self._require()
        full = self._sanitize_path(path)
        clean = full[len(CONTAINER_WORKDIR):].lstrip("/")
        payload = content.encode()

        def _put():
            buf = io.BytesIO()
            with tarfile.open(fileobj=buf, mode="w") as tar:
                info = tarfile.TarInfo(name=clean)
                info.size = len(payload)
                info.mtime = int(time.time())
                tar.addfile(info, io.BytesIO(payload))
            buf.seek(0)
            parent = "/".join(clean.split("/")[:-1])
            if parent:
                container.exec_run(["/bin/sh", "-lc", f"mkdir -p {shlex.quote(CONTAINER_WORKDIR + '/' + parent)}"])
            container.put_archive(CONTAINER_WORKDIR, buf.read())

        await asyncio.to_thread(_put)
        return len(payload)

    async def list_dir(self, path: str = "") -> list[FileEntry]:
        target = f"{CONTAINER_WORKDIR}/{path.strip('/')}" if path else CONTAINER_WORKDIR
        script = (
            f"cd {shlex.quote(target)} 2>/dev/null || exit 0; "
            "for f in * .*; do "
            '[ "$f" = "." ] || [ "$f" = ".." ] || [ ! -e "$f" ] && continue; '
            'if [ -d "$f" ]; then echo "d|$f|0"; else echo "f|$f|$(wc -c < "$f" 2>/dev/null || echo 0)"; fi; '
            "done"
        )
        res = await self.exec(script, timeout=30)
        entries: list[FileEntry] = []
        prefix = f"{path.strip('/')}/" if path.strip("/") else ""
        for line in res.stdout.splitlines():
            parts = line.split("|", 2)
            if len(parts) != 3:
                continue
            kind, name, size = parts
            entries.append(
                FileEntry(
                    name=name,
                    path=prefix + name,
                    is_dir=kind == "d",
                    size=int(size.strip() or 0) if kind == "f" else 0,
                )
            )
        entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return entries

    async def delete(self, path: str) -> None:
        clean = path.strip("/")
        if not clean:
            raise SandboxError("Refusing to delete the workspace root")
        await self.exec(f"rm -rf {shlex.quote(clean)}", timeout=60)

    async def exists(self, path: str) -> bool:
        res = await self.exec(f"test -e {shlex.quote(path.strip('/'))} && echo yes", timeout=20)
        return "yes" in res.stdout

    async def endpoint(self, port: int) -> str | None:
        container = self._container
        if container is None:
            return None

        def _ip() -> str:
            container.reload()
            networks = (container.attrs.get("NetworkSettings") or {}).get("Networks") or {}
            for net in networks.values():
                if net.get("IPAddress"):
                    return net["IPAddress"]
            return (container.attrs.get("NetworkSettings") or {}).get("IPAddress", "")

        ip = await asyncio.to_thread(_ip)
        return f"http://{ip}:{int(port)}" if ip else None
