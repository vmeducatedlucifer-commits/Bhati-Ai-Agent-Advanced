"""Superserve cloud sandbox backend (Firecracker MicroVMs).

Implements the local Sandbox contract against the public Superserve API
(https://docs.superserve.ai): control plane at `SUPERSERVE_API_URL` with the
team `X-API-Key`, per-sandbox data plane at `boxd-{id}.sandbox.superserve.ai`
with the sandbox `X-Access-Token`.

Auth needed: the user's OWN API key (`ss_live_...` from console Settings →
API keys), stored encrypted via Settings → Sandbox or the env var. No
account farming, no shared keys — one key, one team.
"""

from __future__ import annotations

import asyncio
import shlex
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.sandbox.base import ExecResult, FileEntry, Sandbox, SandboxInfo

log = get_logger("app.sandbox.superserve")

REMOTE_HOME = "/home/user"
REMOTE_ROOT = f"{REMOTE_HOME}/bhati"
SYNC_MAX_FILES = 200
SYNC_MAX_BYTES = 10_000_000
SYNC_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".cache"}


class SuperserveError(Exception):
    def __init__(self, message: str, *, code: str = "error", status: int = 0):
        super().__init__(message)
        self.code = code
        self.status = status


def _api_error(status: int, payload: Any, action: str) -> SuperserveError:
    code, message = "error", f"{action} failed (HTTP {status})"
    if isinstance(payload, dict):
        err = payload.get("error") or {}
        code = str(err.get("code") or code)
        message = str(err.get("message") or message)
    return SuperserveError(message, code=code, status=status)


class SuperserveClient:
    """Thin async wrapper over the control + data planes."""

    def __init__(self, api_key: str, base_url: str = ""):
        if not api_key:
            raise SuperserveError("Superserve API key is not configured", code="no_key")
        self.api_key = api_key
        self.base_url = (base_url or settings.SUPERSERVE_API_URL).rstrip("/")

    def _control_headers(self) -> dict[str, str]:
        return {"X-API-Key": self.api_key, "User-Agent": "BhatiAiAgent/2.0"}

    def _data_headers(self, access_token: str, sandbox_id: str = "") -> dict[str, str]:
        headers = {"X-Access-Token": access_token, "User-Agent": "BhatiAiAgent/2.0"}
        if sandbox_id:
            headers["X-Superserve-Sandbox-Id"] = sandbox_id
        return headers

    def _box_host(self, sandbox_id: str) -> str:
        return f"https://boxd-{sandbox_id}.sandbox.superserve.ai"

    async def _request(
        self, method: str, url: str, *, headers: dict[str, str], **kwargs: Any
    ) -> Any:
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                response = await client.request(method, url, headers=headers, **kwargs)
        except Exception as exc:
            raise SuperserveError(f"Network error: {exc}", code="network") from exc
        if response.status_code >= 400:
            try:
                payload = response.json()
            except ValueError:
                payload = {"error": {"message": response.text[:300]}}
            raise _api_error(response.status_code, payload, f"{method} {url}")
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return {"text": response.text}

    # ---- control plane (X-API-Key) ------------------------------------

    async def create(
        self,
        name: str,
        *,
        template: str = "",
        metadata: dict[str, str] | None = None,
        timeout_seconds: int = 0,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"name": name[:64]}
        if template:
            body["from_template"] = template
        if metadata:
            body["metadata"] = metadata
        if timeout_seconds > 0:
            body["timeout_seconds"] = timeout_seconds
        data = await self._request(
            "POST", f"{self.base_url}/sandboxes",
            headers=self._control_headers(), json=body,
        )
        if not isinstance(data, dict) or not data.get("id"):
            raise SuperserveError("Create returned no sandbox id", code="bad_response")
        return data

    async def get(self, sandbox_id: str) -> dict[str, Any]:
        data = await self._request(
            "GET", f"{self.base_url}/sandboxes/{sandbox_id}",
            headers=self._control_headers(),
        )
        return data if isinstance(data, dict) else {}

    async def activate(self, sandbox_id: str) -> dict[str, Any]:
        """Resume-if-paused + fresh access token."""
        data = await self._request(
            "POST", f"{self.base_url}/sandboxes/{sandbox_id}/activate",
            headers=self._control_headers(), json={},
        )
        return data if isinstance(data, dict) else {}

    async def delete(self, sandbox_id: str) -> None:
        try:
            await self._request(
                "DELETE", f"{self.base_url}/sandboxes/{sandbox_id}",
                headers=self._control_headers(),
            )
        except SuperserveError as exc:
            if exc.status != 404:
                raise

    async def pause(self, sandbox_id: str) -> None:
        try:
            await self._request(
                "POST", f"{self.base_url}/sandboxes/{sandbox_id}/pause",
                headers=self._control_headers(), json={},
            )
        except SuperserveError as exc:
            if exc.status != 404:
                raise

    async def list(self, *, metadata: dict[str, str] | None = None) -> list[dict[str, Any]]:
        params = {f"metadata.{k}": v for k, v in (metadata or {}).items()}
        data = await self._request(
            "GET", f"{self.base_url}/sandboxes",
            headers=self._control_headers(), params=params,
        )
        if isinstance(data, dict) and isinstance(data.get("sandboxes"), list):
            return [s for s in data["sandboxes"] if isinstance(s, dict)]
        return data if isinstance(data, list) else []

    async def publish_port(self, sandbox_id: str, port: int) -> None:
        await self._request(
            "POST", f"{self.base_url}/sandboxes/{sandbox_id}/preview-ports",
            headers=self._control_headers(), json={"port": port},
        )

    async def list_dir(self, sandbox_id: str, path: str) -> list[dict[str, Any]]:
        data = await self._request(
            "GET", f"{self.base_url}/sandboxes/{sandbox_id}/files",
            headers=self._control_headers(), params={"path": path or "/"},
        )
        if isinstance(data, dict) and isinstance(data.get("entries"), list):
            return [e for e in data["entries"] if isinstance(e, dict)]
        return []

    # ---- data plane (X-Access-Token) -----------------------------------

    async def exec(
        self,
        sandbox_id: str,
        access_token: str,
        command: str,
        *,
        working_dir: str = REMOTE_HOME,
        timeout_s: int = 300,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        started = time.time()
        try:
            data = await self._request(
                "POST", f"{self._box_host(sandbox_id)}/exec",
                headers=self._data_headers(access_token),
                json={
                    "command": command, "working_dir": working_dir,
                    "timeout_s": max(1, timeout_s), "env": env or {},
                },
            )
        except SuperserveError as exc:
            if exc.status == 503:
                # Paused mid-run: activate (fresh token) and retry once.
                fresh = await self.activate(sandbox_id)
                token = str(fresh.get("access_token") or access_token)
                data = await self._request(
                    "POST", f"{self._box_host(sandbox_id)}/exec",
                    headers=self._data_headers(token),
                    json={
                        "command": command, "working_dir": working_dir,
                        "timeout_s": max(1, timeout_s), "env": env or {},
                    },
                )
                if isinstance(data, dict):
                    data["_access_token"] = token
            else:
                raise
        if isinstance(data, dict):
            data["_duration_ms"] = int((time.time() - started) * 1000)
            return data
        return {"stdout": "", "stderr": str(data), "exit_code": 1}

    async def exec_stream(
        self, sandbox_id: str, access_token: str, command: str, *,
        working_dir: str = REMOTE_HOME, timeout_s: int = 300,
        env: dict[str, str] | None = None,
    ) -> AsyncIterator[str]:
        import json as json_lib

        url = f"{self._box_host(sandbox_id)}/exec/stream"
        body = {
            "command": command, "working_dir": working_dir,
            "timeout_s": max(1, timeout_s), "env": env or {},
        }
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream(
                    "POST", url, headers=self._data_headers(access_token), json=body
                ) as response:
                    if response.status_code >= 400:
                        text = (await response.aread()).decode("utf-8", "ignore")[:300]
                        raise SuperserveError(
                            f"Stream failed (HTTP {response.status_code}): {text}",
                            code="stream_failed", status=response.status_code,
                        )
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        try:
                            event = json_lib.loads(line[5:].strip())
                        except ValueError:
                            continue
                        if "stdout" in event:
                            yield str(event["stdout"])
                        elif "stderr" in event:
                            yield str(event["stderr"])
                        elif event.get("finished"):
                            if event.get("exit_code") not in (None, 0):
                                yield f"\n[exit {event.get('exit_code')}]\n"
                            if event.get("error"):
                                yield f"\n[error: {event.get('error')}]\n"
                            return
        except SuperserveError:
            raise
        except Exception as exc:
            raise SuperserveError(f"Stream failed: {exc}", code="stream_failed") from exc

    async def read_file(self, sandbox_id: str, access_token: str, path: str) -> bytes:
        try:
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                response = await client.get(
                    f"{self._box_host(sandbox_id)}/files",
                    headers=self._data_headers(access_token), params={"path": path},
                )
        except Exception as exc:
            raise SuperserveError(f"Network error: {exc}", code="network") from exc
        if response.status_code >= 400:
            raise _api_error(response.status_code, {}, f"GET /files {path}")
        return response.content

    async def write_file(
        self, sandbox_id: str, access_token: str, path: str, content: bytes
    ) -> int:
        data = await self._request(
            "POST", f"{self._box_host(sandbox_id)}/files",
            headers={**self._data_headers(access_token),
                     "Content-Type": "application/octet-stream"},
            params={"path": path}, content=content,
        )
        if isinstance(data, dict) and isinstance(data.get("size"), int):
            return int(data["size"])
        return len(content)


@dataclass
class PooledBox:
    id: str
    access_token: str
    healthy: bool = True


class SuperserveSandbox(Sandbox):
    """One agent workspace on a Superserve MicroVM.

    Remote paths live under /home/user/bhati; `workdir` reports the local
    workspace path so the rest of the app keeps working, while exec/files
    run against the remote root. Local files sync up once at start (capped).
    """

    def __init__(
        self,
        thread_id: str,
        workspace: str,
        client: SuperserveClient,
        *,
        box_id: str = "",
        access_token: str = "",
    ):
        self.id = f"superserve-{thread_id}"
        self.workdir = workspace
        self._thread_id = thread_id
        self._client = client
        self._box_id = box_id
        self._token = access_token
        self._started_at = 0.0

    # ---- paths ---------------------------------------------------------

    def _abs(self, path: str) -> str:
        rel = (path or "").lstrip("/")
        return f"{REMOTE_ROOT}/{rel}" if rel else REMOTE_ROOT

    def _rel(self, remote_path: str) -> str:
        prefix = REMOTE_ROOT + "/"
        if remote_path.startswith(prefix):
            return remote_path[len(prefix):]
        return remote_path.lstrip("/")

    # ---- lifecycle ------------------------------------------------------

    async def start(self) -> SandboxInfo:
        if self._box_id:
            fresh = await self._client.activate(self._box_id)
            token = str(fresh.get("access_token") or self._token)
            if token:
                self._token = token
        else:
            created = await self._client.create(
                f"bhati-{self._thread_id[:16]}",
                template=settings.SUPERSERVE_TEMPLATE,
                metadata={"thread": self._thread_id, "app": "bhati-ai-agent"},
            )
            self._box_id = str(created["id"])
            self._token = str(created.get("access_token") or "")
            if not self._token:
                fresh = await self._client.activate(self._box_id)
                self._token = str(fresh.get("access_token") or "")
        if not self._box_id or not self._token:
            raise SuperserveError("Sandbox created without id/token", code="bad_response")
        await self._sync_up()
        self._started_at = time.time()
        return await self.info()

    async def _sync_up(self) -> None:
        """Copy the local workspace into the fresh remote root (capped)."""
        local = Path(self.workdir)
        if not local.is_dir():
            return
        files: list[Path] = []
        total = 0
        for path in sorted(local.rglob("*")):
            if len(files) >= SYNC_MAX_FILES or total >= SYNC_MAX_BYTES:
                break
            if not path.is_file() or path.is_symlink():
                continue
            if any(part in SYNC_SKIP_DIRS or part.startswith(".") for part in path.parts[len(local.parts):-1]):
                continue
            size = path.stat().st_size
            if size > 1_000_000:
                continue
            files.append(path)
            total += size
        for path in files:
            try:
                rel = path.relative_to(local).as_posix()
                await self._client.write_file(
                    self._box_id, self._token, self._abs(rel), path.read_bytes()
                )
            except Exception as exc:
                log.warning("sync-up skipped %s: %s", path, exc)

    async def stop(self, *, remove: bool = True) -> None:
        if not self._box_id:
            return
        try:
            if remove:
                await self._client.delete(self._box_id)
            else:
                await self._client.pause(self._box_id)
        finally:
            self._box_id = ""
            self._token = ""

    async def info(self) -> SandboxInfo:
        status, detail = "starting", {}
        if self._box_id:
            try:
                data = await self._client.get(self._box_id)
                status = str(data.get("status", "active"))
                detail = {
                    "vcpu": data.get("vcpu_count"),
                    "memory_mib": data.get("memory_mib"),
                    "box_id": self._box_id,
                }
            except SuperserveError as exc:
                status = f"error: {exc.code}"
        return SandboxInfo(
            id=self.id, backend="superserve", status=status,
            workspace=self.workdir, image=settings.SUPERSERVE_TEMPLATE,
            started_at=self._started_at, detail=detail,
        )

    # ---- exec -------------------------------------------------------------

    async def exec(
        self, command: str, *, cwd: str | None = None,
        timeout: int | None = None, env: dict[str, str] | None = None,
    ) -> ExecResult:
        timeout = timeout or settings.SANDBOX_COMMAND_TIMEOUT_S
        working_dir = self._abs(cwd) if cwd else REMOTE_ROOT
        try:
            data = await self._client.exec(
                self._box_id, self._token, command,
                working_dir=working_dir, timeout_s=timeout, env=env,
            )
        except SuperserveError as exc:
            return ExecResult(exit_code=1, stderr=f"superserve: {exc}")
        if "_access_token" in data and data["_access_token"]:
            self._token = str(data["_access_token"])
        stderr = str(data.get("stderr") or "")
        if data.get("truncated"):
            stderr += "\n[output truncated by server — use streaming for full logs]"
        return ExecResult(
            exit_code=int(data.get("exit_code", 1)),
            stdout=str(data.get("stdout") or ""),
            stderr=stderr,
            duration_ms=int(data.get("_duration_ms", 0)),
        )

    def exec_stream(
        self, command: str, *, cwd: str | None = None,
        timeout: int | None = None, env: dict[str, str] | None = None,
    ) -> AsyncIterator[str]:
        return self._exec_stream_gen(command, cwd=cwd, timeout=timeout, env=env)

    async def _exec_stream_gen(
        self, command: str, *, cwd: str | None = None,
        timeout: int | None = None, env: dict[str, str] | None = None,
    ) -> AsyncIterator[str]:
        timeout = timeout or settings.SANDBOX_COMMAND_TIMEOUT_S
        working_dir = self._abs(cwd) if cwd else REMOTE_ROOT
        try:
            async for chunk in self._client.exec_stream(
                self._box_id, self._token, command,
                working_dir=working_dir, timeout_s=timeout, env=env,
            ):
                yield chunk
        except SuperserveError as exc:
            yield f"\n[superserve error: {exc}]\n"

    # ---- files --------------------------------------------------------------

    async def read_file(self, path: str, *, max_bytes: int = 2_000_000) -> str:
        raw = await self._client.read_file(self._box_id, self._token, self._abs(path))
        return raw[:max_bytes].decode("utf-8", errors="replace")

    async def write_file(self, path: str, content: str) -> int:
        return await self._client.write_file(
            self._box_id, self._token, self._abs(path), content.encode("utf-8")
        )

    async def list_dir(self, path: str = "") -> list[FileEntry]:
        entries = await self._client.list_dir(self._box_id, self._abs(path))
        out: list[FileEntry] = []
        for entry in entries:
            name = str(entry.get("name", ""))
            base = (path.rstrip("/") + "/" + name).lstrip("/") if path else name
            out.append(
                FileEntry(
                    name=name, path=base,
                    is_dir=bool(entry.get("is_dir", False)),
                    size=int(entry.get("size") or 0),
                    modified=float(entry.get("modified_unix") or 0),
                )
            )
        out.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return out

    async def delete(self, path: str) -> None:
        target = self._abs(path).strip()
        if target in ("", "/", REMOTE_ROOT):
            raise SuperserveError("Refusing to delete the workspace root", code="bad_path")
        result = await self.exec(f"rm -rf -- {shlex.quote(target)}", timeout=60)
        if not result.ok:
            raise SuperserveError(result.stderr or "delete failed", code="delete_failed")

    async def exists(self, path: str) -> bool:
        parent, _, name = (path or "").rstrip("/").rpartition("/")
        try:
            entries = await self.list_dir(parent)
        except SuperserveError:
            return False
        return any(e.name == name for e in entries)

    async def endpoint(self, port: int) -> str | None:
        try:
            await self._client.publish_port(self._box_id, port)
            return f"https://{port}-{self._box_id}.sandbox.superserve.ai"
        except SuperserveError as exc:
            log.warning("preview publish failed: %s", exc)
            return None


@dataclass
class SuperservePool:
    """Warm standby pool of cloud sandboxes.

    Boxes are blank (no thread data); a lease hands one to a thread and the
    box syncs that thread's workspace on start. Released boxes are always
    deleted (never recycled dirty) and the background top-up replaces them.
    Quota errors back off instead of hot-looping.
    """

    client: SuperserveClient
    size: int = 5
    template: str = ""
    boxes: list[PooledBox] = field(default_factory=list)
    quota_exhausted: bool = False
    last_error: str = ""
    _task: asyncio.Task | None = field(default=None, repr=False)

    async def _health(self, box: PooledBox) -> bool:
        try:
            data = await self.client.get(box.id)
            return str(data.get("status", "")) == "active"
        except SuperserveError:
            return False

    async def _make_one(self) -> PooledBox | None:
        try:
            created = await self.client.create(
                f"bhati-pool-{int(time.time()) % 100000}",
                template=self.template or settings.SUPERSERVE_TEMPLATE,
                metadata={"app": "bhati-ai-agent", "pool": "warm"},
            )
            box_id = str(created.get("id", ""))
            token = str(created.get("access_token") or "")
            if not box_id:
                return None
            if not token:
                fresh = await self.client.activate(box_id)
                token = str(fresh.get("access_token") or "")
            return PooledBox(id=box_id, access_token=token) if token else None
        except SuperserveError as exc:
            self.last_error = str(exc)
            if exc.code == "too_many_sandboxes" or exc.status == 429:
                self.quota_exhausted = True
            log.warning("pool create failed: %s", exc)
            return None

    async def maintain(self) -> None:
        """One pass: drop unhealthy boxes, top up to size (unless quota-hit)."""
        kept: list[PooledBox] = []
        for box in self.boxes:
            if await self._health(box):
                kept.append(box)
            else:
                try:
                    await self.client.delete(box.id)
                except SuperserveError:
                    pass
        self.boxes = kept
        if self.quota_exhausted:
            # Probe recovery with a single create instead of hammering.
            probe = await self._make_one()
            if probe is None:
                return
            self.boxes.append(probe)
            self.quota_exhausted = False
            self.last_error = ""
        while len(self.boxes) < max(0, self.size):
            box = await self._make_one()
            if box is None:
                break
            self.boxes.append(box)

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(30)
                await self.maintain()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover
                log.warning("pool loop error: %s", exc)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop(), name="superserve-pool")

    async def shutdown(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        for box in self.boxes:
            try:
                await self.client.delete(box.id)
            except SuperserveError:
                pass
        self.boxes = []

    async def acquire(self) -> PooledBox | None:
        while self.boxes:
            box = self.boxes.pop(0)
            if await self._health(box):
                return box
            try:
                await self.client.delete(box.id)
            except SuperserveError:
                pass
        return await self._make_one()

    def status(self) -> dict[str, Any]:
        return {
            "size": self.size,
            "warm": len(self.boxes),
            "quota_exhausted": self.quota_exhausted,
            "last_error": self.last_error,
        }
