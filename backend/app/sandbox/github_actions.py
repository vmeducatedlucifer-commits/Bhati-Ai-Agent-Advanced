"""GitHub Actions sandbox backend (free cloud runners, minutes per command).

Unlike the old fire-and-forget dispatch, this is a real Sandbox: every exec
gets a unique run id, the workflow uploads a result artifact, and we poll the
run to completion and download the artifact back. Files go through the repo
Contents API, so the whole Sandbox contract works.

Honest limits (shown in the UI too): each command queues a fresh runner
(~30-120s overhead), so this suits heavy background jobs — not interactive
typing. Free accounts get ~2000 runner minutes/month.
"""

from __future__ import annotations

import asyncio
import base64
import io
import time
import zipfile
from collections.abc import AsyncIterator
from typing import Any

from app.core.logging import get_logger
from app.sandbox.base import ExecResult, FileEntry, Sandbox, SandboxInfo

log = get_logger("app.sandbox.github")

WORKFLOW_PATH = ".github/workflows/sandbox-runner.yml"
POLL_INTERVAL_S = 10
FIND_TIMEOUT_S = 180

WORKFLOW_YAML = """name: Rawal AI Sandbox Runner

on:
  workflow_dispatch:
    inputs:
      run_id:
        description: 'Unique id for this exec (used for run name + artifact)'
        required: true
        type: string
      command:
        description: 'Command to execute in the runner workspace'
        required: true
        type: string

run-name: "bhati-${{ inputs.run_id }}"

jobs:
  run-sandbox:
    name: Execute agent command
    runs-on: ubuntu-latest
    timeout-minutes: 30
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'

      - name: Execute and capture
        env:
          BHATI_COMMAND: ${{ inputs.command }}
          BHATI_RUN_ID: ${{ inputs.run_id }}
        run: |
          set +e
          bash -c "$BHATI_COMMAND" > /tmp/bhati-stdout.txt 2> /tmp/bhati-stderr.txt
          code=$?
          python3 - "$code" <<'EOF'
          import json, sys
          code = int(sys.argv[1])
          with open('/tmp/bhati-stdout.txt', encoding='utf-8', errors='replace') as f:
              stdout = f.read()[-400000:]
          with open('/tmp/bhati-stderr.txt', encoding='utf-8', errors='replace') as f:
              stderr = f.read()[-100000:]
          with open('bhati-result.json', 'w', encoding='utf-8') as f:
              json.dump({'stdout': stdout, 'stderr': stderr, 'exit_code': code}, f)
          EOF

      - name: Upload result
        uses: actions/upload-artifact@v4
        with:
          name: bhati-result-${{ inputs.run_id }}
          path: bhati-result.json
          retention-days: 1
"""


def find_run(runs: list[dict[str, Any]], run_id: str) -> dict[str, Any] | None:
    """Match our dispatched run by its unique run-name marker."""
    marker = f"bhati-{run_id}"
    for run in runs:
        if not isinstance(run, dict):
            continue
        if run.get("display_title") == marker or run.get("name") == marker:
            return run
    return None


def parse_result_artifact(zip_bytes: bytes) -> dict[str, Any]:
    """Extract result.json from a downloaded artifact archive."""
    if len(zip_bytes) > 20_000_000:
        raise ValueError("artifact archive exceeds 20 MB")
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        members = zf.infolist()
        if len(members) > 100:
            raise ValueError("artifact archive has too many files")
        if sum(m.file_size for m in members) > 10_000_000:
            raise ValueError("artifact uncompresses past 10 MB")
        for name in zf.namelist():
            if name.rsplit("/", 1)[-1] == "bhati-result.json":
                import json as json_lib

                data = json_lib.loads(zf.read(name).decode("utf-8"))
                if isinstance(data, dict):
                    return data
    raise ValueError("bhati-result.json not found in artifact")


class GitHubActionsSandbox(Sandbox):
    """Sandbox whose exec/files live in a GitHub repo + Actions runners."""

    def __init__(self, thread_id: str, workspace: str, client: Any, repo: str):
        self.id = f"github-{thread_id}"
        self.workdir = workspace
        self._thread_id = thread_id
        self._client = client
        self._repo = repo
        self._ref = ""
        self._started_at = 0.0
        self._run_seq = 0

    # ---- setup ----------------------------------------------------------

    async def start(self) -> SandboxInfo:
        repo_info = await self._client.request("GET", f"/repos/{self._repo}")
        self._ref = str(repo_info.get("default_branch") or "main")
        try:
            await self._client.request(
                "GET", f"/repos/{self._repo}/contents/{WORKFLOW_PATH}"
            )
        except Exception:
            log.info("installing sandbox-runner.yml into %s", self._repo)
            await self._client.request(
                "PUT", f"/repos/{self._repo}/contents/{WORKFLOW_PATH}",
                json={
                    "message": "Add Rawal AI sandbox runner",
                    "content": base64.b64encode(WORKFLOW_YAML.encode()).decode(),
                },
            )
        self._started_at = time.time()
        return await self.info()

    async def stop(self, *, remove: bool = True) -> None:
        return None

    async def info(self) -> SandboxInfo:
        return SandboxInfo(
            id=self.id, backend="github", status="active",
            workspace=self.workdir, image="ubuntu-latest",
            started_at=self._started_at,
            detail={"repo": self._repo, "note": "free runners: minutes per command"},
        )

    # ---- runs --------------------------------------------------------------

    async def _list_runs(self) -> list[dict[str, Any]]:
        data = await self._client.request(
            "GET",
            f"/repos/{self._repo}/actions/workflows/sandbox-runner.yml/runs",
            params={"event": "workflow_dispatch", "per_page": 30},
        )
        runs = (data or {}).get("workflow_runs", []) if isinstance(data, dict) else []
        return [r for r in runs if isinstance(r, dict)]

    async def _wait_for_run(self, run_id: str, timeout: int) -> dict[str, Any]:
        deadline = time.time() + max(30, timeout)
        find_deadline = time.time() + FIND_TIMEOUT_S
        while True:
            run = find_run(await self._list_runs(), run_id)
            if run is not None:
                if str(run.get("status", "")) == "completed":
                    return run
                if time.time() > deadline:
                    raise TimeoutError(f"github run {run_id} did not finish in time")
            elif time.time() > find_deadline:
                raise TimeoutError(f"github run {run_id} never appeared")
            await asyncio.sleep(POLL_INTERVAL_S)

    async def _download_result(self, run: dict[str, Any]) -> dict[str, Any]:
        run_id = run.get("id")
        data = await self._client.request(
            "GET", f"/repos/{self._repo}/actions/runs/{run_id}/artifacts",
        )
        artifacts = (data or {}).get("artifacts", []) if isinstance(data, dict) else []
        artifact = next(
            (a for a in artifacts if isinstance(a, dict) and a.get("name", "").startswith("bhati-result-")),
            None,
        )
        if artifact is None:
            raise ValueError("result artifact not found")
        zip_bytes = await self._client.request_bytes(
            "GET", f"/repos/{self._repo}/actions/artifacts/{artifact['id']}/zip"
        )
        return parse_result_artifact(zip_bytes)

    async def _dispatch(self, command: str) -> str:
        import uuid

        self._run_seq += 1
        run_id = f"{int(time.time())}-{self._run_seq}-{uuid.uuid4().hex[:8]}"
        await self._client.request(
            "POST",
            f"/repos/{self._repo}/actions/workflows/sandbox-runner.yml/dispatches",
            json={"ref": self._ref or "main", "inputs": {"run_id": run_id, "command": command[:8000]}},
        )
        return run_id

    # ---- exec ------------------------------------------------------------------

    async def exec(
        self, command: str, *, cwd: str | None = None,
        timeout: int | None = None, env: dict[str, str] | None = None,
    ) -> ExecResult:
        from app.core.config import settings

        timeout = timeout or settings.SANDBOX_COMMAND_TIMEOUT_S
        full = f"cd {self._sh(cwd or '')} && {command}" if cwd else command
        if env:
            prefix = " ".join(f"{k}={self._sh(v)}" for k, v in env.items())
            full = f"{prefix} {full}"
        started = time.time()
        try:
            run_id = await self._dispatch(full)
            run = await self._wait_for_run(run_id, timeout)
            if str(run.get("conclusion", "")) not in ("success", ""):
                pass  # still try the artifact; exit_code inside tells the truth
            try:
                result = await self._download_result(run)
            except Exception as exc:
                return ExecResult(
                    exit_code=1, stderr=f"github run {run.get('conclusion')}: {exc}",
                    duration_ms=int((time.time() - started) * 1000),
                )
            return ExecResult(
                exit_code=int(result.get("exit_code", 1)),
                stdout=str(result.get("stdout") or ""),
                stderr=str(result.get("stderr") or ""),
                duration_ms=int((time.time() - started) * 1000),
            )
        except TimeoutError as exc:
            return ExecResult(
                exit_code=124, stderr=f"Command timed out: {exc}",
                duration_ms=int((time.time() - started) * 1000), timed_out=True,
            )
        except Exception as exc:
            return ExecResult(exit_code=1, stderr=f"github backend: {exc}")

    @staticmethod
    def _sh(value: str) -> str:
        import shlex

        return shlex.quote(value)

    def exec_stream(
        self, command: str, *, cwd: str | None = None,
        timeout: int | None = None, env: dict[str, str] | None = None,
    ) -> AsyncIterator[str]:
        return self._exec_stream_gen(command, cwd=cwd, timeout=timeout, env=env)

    async def _exec_stream_gen(
        self, command: str, *, cwd: str | None = None,
        timeout: int | None = None, env: dict[str, str] | None = None,
    ) -> AsyncIterator[str]:
        yield "[github runner queued — live streaming is not supported, output arrives on completion]\n"
        result = await self.exec(command, cwd=cwd, timeout=timeout, env=env)
        if result.stdout:
            yield result.stdout
        if result.stderr:
            yield f"\n[stderr]\n{result.stderr}"
        if result.exit_code != 0:
            yield f"\n[exit {result.exit_code}]\n"

    # ---- files (repo Contents API) -----------------------------------------------

    def _contents_url(self, path: str) -> str:
        clean = (path or "").strip("/")
        return f"/repos/{self._repo}/contents/{clean}" if clean else f"/repos/{self._repo}/contents"

    async def read_file(self, path: str, *, max_bytes: int = 2_000_000) -> str:
        data = await self._client.request("GET", self._contents_url(path))
        if not isinstance(data, dict) or data.get("type") not in (None, "file"):
            raise ValueError(f"not a file: {path}")
        content = base64.b64decode(data.get("content") or "").decode("utf-8", errors="replace")
        return content[:max_bytes]

    async def write_file(self, path: str, content: str) -> int:
        raw = content.encode("utf-8")
        sha: str | None = None
        try:
            existing = await self._client.request("GET", self._contents_url(path))
            if isinstance(existing, dict):
                sha = str(existing.get("sha") or "") or None
        except Exception:
            sha = None
        body: dict[str, Any] = {
            "message": f"Rawal AI: update {path}",
            "content": base64.b64encode(raw).decode(),
        }
        if sha:
            body["sha"] = sha
        await self._client.request("PUT", self._contents_url(path), json=body)
        return len(raw)

    async def list_dir(self, path: str = "") -> list[FileEntry]:
        data = await self._client.request("GET", self._contents_url(path))
        nodes = data if isinstance(data, list) else []
        out: list[FileEntry] = []
        base = (path or "").strip("/")
        for node in nodes:
            if not isinstance(node, dict):
                continue
            name = str(node.get("name", ""))
            full = f"{base}/{name}".lstrip("/") if base else name
            out.append(
                FileEntry(
                    name=name, path=full,
                    is_dir=str(node.get("type", "")) == "dir",
                    size=int(node.get("size") or 0),
                )
            )
        out.sort(key=lambda e: (not e.is_dir, e.name.lower()))
        return out

    async def delete(self, path: str) -> None:
        clean = (path or "").strip("/")
        if not clean:
            raise ValueError("Refusing to delete the repository root")
        existing = await self._client.request("GET", self._contents_url(clean))
        if not isinstance(existing, dict) or not existing.get("sha"):
            raise ValueError(f"not found: {path}")
        await self._client.request(
            "DELETE", self._contents_url(clean),
            json={"message": f"Rawal AI: delete {clean}", "sha": existing["sha"]},
        )

    async def exists(self, path: str) -> bool:
        try:
            await self._client.request("GET", self._contents_url(path))
            return True
        except Exception:
            return False

    async def endpoint(self, port: int) -> str | None:
        return None
