"""Host-process sandbox: no isolation, used when Docker is unavailable.

Everything is confined to a workspace directory and paths are resolved so the agent
cannot escape it with `..`.
"""

from __future__ import annotations

import asyncio
import shutil
import time
from collections.abc import AsyncIterator
from pathlib import Path

from app.core.config import settings
from app.core.env import sandbox_env
from app.core.errors import AppError
from app.core.logging import get_logger
from app.sandbox.base import ExecResult, FileEntry, Sandbox, SandboxInfo

log = get_logger("app.sandbox.local")


class LocalSandbox(Sandbox):
    backend = "local"

    def __init__(self, sandbox_id: str, workspace: str):
        self.id = sandbox_id
        self.root = Path(workspace).resolve()
        self.workdir = str(self.root)
        self._started_at = 0.0

    # ---- lifecycle -------------------------------------------------------

    async def start(self) -> SandboxInfo:
        self.root.mkdir(parents=True, exist_ok=True)
        self._started_at = time.time()
        return await self.info()

    async def stop(self, *, remove: bool = True) -> None:
        self._started_at = 0.0

    async def info(self) -> SandboxInfo:
        return SandboxInfo(
            id=self.id,
            backend=self.backend,
            status="running" if self._started_at else "stopped",
            workspace=str(self.root),
            started_at=self._started_at,
            detail={"isolated": False},
        )

    # ---- paths -----------------------------------------------------------

    def resolve(self, path: str | None) -> Path:
        candidate = (self.root / (path or "")).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise AppError(f"Path escapes workspace: {path}", code="path_escape")
        return candidate

    def relative(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root))
        except ValueError:
            return path.name

    # ---- exec ------------------------------------------------------------

    async def exec(
        self,
        command: str,
        *,
        cwd: str | None = None,
        timeout: int | None = None,
        env: dict[str, str] | None = None,
    ) -> ExecResult:
        timeout = timeout or settings.SANDBOX_COMMAND_TIMEOUT_S
        started = time.perf_counter()
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(self.resolve(cwd)),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={**sandbox_env(), **(env or {})},
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return ExecResult(
                exit_code=124,
                stdout="",
                stderr=f"Command timed out after {timeout}s",
                duration_ms=int((time.perf_counter() - started) * 1000),
                timed_out=True,
            )
        return ExecResult(
            exit_code=proc.returncode or 0,
            stdout=out.decode(errors="replace"),
            stderr=err.decode(errors="replace"),
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
        timeout = timeout or settings.SANDBOX_COMMAND_TIMEOUT_S
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(self.resolve(cwd)),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env={**sandbox_env(), **(env or {})},
        )
        assert proc.stdout is not None
        deadline = time.time() + timeout
        try:
            while True:
                if time.time() > deadline:
                    proc.kill()
                    yield f"\n[timed out after {timeout}s]\n"
                    break
                try:
                    chunk = await asyncio.wait_for(proc.stdout.read(4096), timeout=1.0)
                except TimeoutError:
                    if proc.returncode is not None:
                        break
                    continue
                if not chunk:
                    break
                yield chunk.decode(errors="replace")
        finally:
            if proc.returncode is None:
                proc.kill()
            await proc.wait()

    # ---- files -----------------------------------------------------------

    async def read_file(self, path: str, *, max_bytes: int = 2_000_000) -> str:
        target = self.resolve(path)
        if not target.is_file():
            raise AppError(f"Not a file: {path}", code="not_a_file", status_code=404)
        data = await asyncio.to_thread(target.read_bytes)
        text = data[:max_bytes].decode("utf-8", errors="replace")
        # Normalize CRLF to LF for consistent cross-platform behavior
        return text.replace("\r\n", "\n")

    async def write_file(self, path: str, content: str) -> int:
        target = self.resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Normalize to LF to keep cross-platform consistency
        raw = content.encode("utf-8")
        await asyncio.to_thread(target.write_bytes, raw)
        return len(raw)

    async def list_dir(self, path: str = "") -> list[FileEntry]:
        target = self.resolve(path)
        if not target.is_dir():
            return []
        entries: list[FileEntry] = []
        for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            try:
                stat = child.stat()
            except OSError:
                continue
            entries.append(
                FileEntry(
                    name=child.name,
                    path=self.relative(child),
                    is_dir=child.is_dir(),
                    size=0 if child.is_dir() else stat.st_size,
                    modified=stat.st_mtime,
                )
            )
        return entries

    async def delete(self, path: str) -> None:
        target = self.resolve(path)
        if target == self.root:
            raise AppError("Refusing to delete the workspace root", code="refused")
        if target.is_dir():
            await asyncio.to_thread(shutil.rmtree, target, True)
        elif target.exists():
            await asyncio.to_thread(target.unlink)

    async def exists(self, path: str) -> bool:
        return self.resolve(path).exists()

    async def endpoint(self, port: int) -> str | None:
        return f"http://127.0.0.1:{int(port)}"
