"""GitHub integration for automated workspace backup, repository binding, and GitHub Actions Cloud Sandbox.

Allows Rawal AI to securely create private/public repositories using the user's
GitHub token, automatically sync workspace files, and offload heavy commands/builds/tests
to isolated GitHub Cloud Runners (saving Render free tier RAM from crashing).
"""

from __future__ import annotations

import asyncio
import logging
import shlex
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select

from app.core.config import settings
from app.core.crypto import decrypt
from app.db.models import Connector, Project
from app.db.session import SessionLocal

log = logging.getLogger("app.storage.github")

WORKFLOW_CONTENT = """name: Rawal AI Sandbox Runner

on:
  workflow_dispatch:
    inputs:
      command:
        description: 'Command to execute in isolated sandbox'
        required: true
        type: string
      project_name:
        description: 'Target project / workspace'
        required: false
        default: 'sandbox-run'

jobs:
  run-sandbox:
    name: Execute in Isolated GitHub Cloud Sandbox
    runs-on: ubuntu-latest
    timeout-minutes: 30

    steps:
      - name: Checkout Code
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'

      - name: Execute Agent Command
        run: |
          echo "=== RUNNING IN GITHUB ACTIONS CLOUD RUNNER ==="
          ${{ inputs.command }}
"""


class GitHubSyncManager:
    def __init__(self) -> None:
        self._cached_token: str = ""
        self._cached_user: str = ""

    async def get_token(self) -> str:
        """Resolve token from DB Connector table or settings.GITHUB_TOKEN."""
        try:
            async with SessionLocal() as db:
                row = (
                    await db.execute(select(Connector).where(Connector.service == "github"))
                ).scalar_one_or_none()
                if row and row.enabled:
                    token = decrypt(row.token_enc)
                    if token:
                        return token
        except Exception:
            pass
        return settings.GITHUB_TOKEN or ""

    async def is_enabled(self) -> bool:
        token = await self.get_token()
        return bool(token)

    async def _headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "BhatiAiAgent-Engine/2.0",
        }

    async def get_username(self, token: str) -> str:
        if self._cached_user and self._cached_token == token:
            return self._cached_user
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get("https://api.github.com/user", headers=await self._headers(token))
                if resp.status_code == 200:
                    username = resp.json().get("login", "")
                    if username:
                        self._cached_user = username
                        self._cached_token = token
                        return username
        except Exception as exc:
            log.warning("Could not fetch GitHub username: %s", exc)
        return ""

    async def ensure_repository(self, project_id: str, project_name: str = "") -> dict[str, Any] | None:
        """Ensure a GitHub repository exists for the project."""
        token = await self.get_token()
        if not token:
            return None

        username = await self.get_username(token)
        if not username:
            return None

        # Determine clean repo name
        clean_name = "".join(c if c.isalnum() or c in ("-", "_") else "-" for c in (project_name or project_id)).strip("-")
        repo_name = f"bhati-{clean_name.lower()[:35]}"

        async with httpx.AsyncClient(timeout=30) as client:
            headers = await self._headers(token)
            # Check if repo exists
            r = await client.get(f"https://api.github.com/repos/{username}/{repo_name}", headers=headers)
            if r.status_code == 200:
                data = r.json()
                return {"full_name": data["full_name"], "clone_url": data["clone_url"], "repo_name": repo_name, "owner": username}

            # Create private repo
            payload = {
                "name": repo_name,
                "description": f"Automated workspace repository for Rawal AI ({project_name or project_id})",
                "private": True,
                "auto_init": False,
            }
            create_res = await client.post("https://api.github.com/user/repos", json=payload, headers=headers)
            if create_res.status_code in (200, 201):
                data = create_res.json()
                log.info("Created new private GitHub repo: %s", data.get("html_url"))
                return {"full_name": data["full_name"], "clone_url": data["clone_url"], "repo_name": repo_name, "owner": username}
            elif create_res.status_code == 422:
                # Repo might exist under another name pattern
                return {"full_name": f"{username}/{repo_name}", "clone_url": f"https://github.com/{username}/{repo_name}.git", "repo_name": repo_name, "owner": username}

        return None

    async def ensure_workflow_file(self, workspace_path: str) -> None:
        """Ensure .github/workflows/sandbox-runner.yml exists in the project workspace."""
        try:
            workflow_dir = Path(workspace_path) / ".github" / "workflows"
            workflow_dir.mkdir(parents=True, exist_ok=True)
            workflow_file = workflow_dir / "sandbox-runner.yml"
            if not workflow_file.exists():
                workflow_file.write_text(WORKFLOW_CONTENT, encoding="utf-8")
        except Exception as exc:
            log.warning("Could not write workflow file to workspace %s: %s", workspace_path, exc)

    async def sync_workspace(self, project_id: str, workspace_path: str, repo_name: str | None = None) -> str | None:
        """Commit and push workspace files to GitHub repository using Git CLI."""
        token = await self.get_token()
        if not token:
            return None

        repo_info = await self.ensure_repository(project_id, repo_name or "")
        if not repo_info:
            return None

        full_name = repo_info["full_name"]
        repo_info["owner"]
        repo_info["repo_name"]

        # Ensure workflow file is in the workspace
        await self.ensure_workflow_file(workspace_path)

        remote_url = f"https://x-access-token:{token}@github.com/{full_name}.git"

        # Execute git commands directly in workspace to sync files
        commands = [
            "git init -q 2>/dev/null || true",
            "git config user.email agent@bhati.local",
            "git config user.name 'Rawal AI'",
            "git add -A",
            'git commit -q -m "Auto-sync from Rawal AI" || true',
            "git branch -M main",
            "git remote remove origin 2>/dev/null || true",
            f"git remote add origin {shlex.quote(remote_url)}",
            "git push -u origin main --force -q",
        ]

        script = " && ".join(commands)

        try:
            proc = await asyncio.create_subprocess_shell(
                script,
                cwd=workspace_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=45)
            if proc.returncode == 0:
                log.info("Successfully synced workspace %s to GitHub repo %s", project_id, full_name)
                # Store repo in DB
                async with SessionLocal() as db:
                    p = await db.get(Project, project_id)
                    if p:
                        p.github_repo = full_name
                        await db.commit()
                return full_name
            else:
                log.warning("Git push sync returned non-zero code: %s - %s", proc.returncode, stderr.decode(errors="replace"))
        except Exception as exc:
            log.error("Git push sync error for project %s: %s", project_id, exc)

        return None

    async def run_in_github_actions(
        self,
        project_id: str,
        workspace_path: str,
        command: str,
        on_chunk: Callable[[str], Coroutine[Any, Any, None]] | None = None,
    ) -> dict[str, Any]:
        """
        Push workspace to GitHub, dispatch sandbox-runner.yml, stream logs live,
        and return output. This runs heavy tasks on GitHub's free runners (0 Render RAM usage).
        """
        token = await self.get_token()
        if not token:
            return {"exit_code": 1, "output": "GitHub Token not found. Add token in Settings → Connectors."}

        full_name = await self.sync_workspace(project_id, workspace_path)
        if not full_name:
            return {"exit_code": 1, "output": "Failed to sync workspace with GitHub repository."}

        headers = await self._headers(token)

        if on_chunk:
            await on_chunk(f"[GitHub Actions] Dispatching cloud runner for command: `{command}` on repo {full_name}...\n")

        async with httpx.AsyncClient(timeout=45) as client:
            # Trigger workflow
            dispatch_url = f"https://api.github.com/repos/{full_name}/actions/workflows/sandbox-runner.yml/dispatches"
            resp = await client.post(
                dispatch_url,
                json={"ref": "main", "inputs": {"command": command, "project_name": project_id}},
                headers=headers,
            )
            if resp.status_code not in (200, 204):
                err = f"Failed to trigger GitHub Actions workflow: {resp.status_code} - {resp.text}"
                if on_chunk:
                    await on_chunk(f"[Error] {err}\n")
                return {"exit_code": 1, "output": err}

            if on_chunk:
                await on_chunk("[GitHub Actions] Cloud runner queued. Waiting for execution...\n")

            # Poll for the dispatched run
            run_id = None
            runs_url = f"https://api.github.com/repos/{full_name}/actions/runs?event=workflow_dispatch&per_page=5"

            for _ in range(25):
                await asyncio.sleep(3)
                r_runs = await client.get(runs_url, headers=headers)
                if r_runs.status_code == 200:
                    runs = r_runs.json().get("workflow_runs", [])
                    if runs:
                        run_id = runs[0]["id"]
                        status = runs[0]["status"]
                        conclusion = runs[0].get("conclusion")
                        if on_chunk and status != "queued":
                            await on_chunk(f"[GitHub Actions] Status: {status}...\n")
                        if status == "completed":
                            break

            if not run_id:
                return {"exit_code": 0, "output": f"Dispatched to GitHub Actions on {full_name}. Check https://github.com/{full_name}/actions"}

            # Poll until completed
            conclusion = None
            for _ in range(120):  # max 10 minutes
                await asyncio.sleep(5)
                run_detail = await client.get(f"https://api.github.com/repos/{full_name}/actions/runs/{run_id}", headers=headers)
                if run_detail.status_code == 200:
                    data = run_detail.json()
                    status = data["status"]
                    conclusion = data.get("conclusion")
                    if status == "completed":
                        break

            # Fetch job logs
            jobs_res = await client.get(f"https://api.github.com/repos/{full_name}/actions/runs/{run_id}/jobs", headers=headers)
            logs_text = ""
            if jobs_res.status_code == 200:
                jobs = jobs_res.json().get("jobs", [])
                if jobs:
                    job_id = jobs[0]["id"]
                    log_res = await client.get(f"https://api.github.com/repos/{full_name}/actions/jobs/{job_id}/logs", headers=headers)
                    if log_res.status_code == 200:
                        logs_text = log_res.text

            final_output = logs_text or f"GitHub Actions finished with conclusion: {conclusion}"
            if on_chunk:
                await on_chunk(f"\n[GitHub Actions Completed: {conclusion}]\n")

            return {
                "exit_code": 0 if conclusion == "success" else 1,
                "output": final_output,
                "url": f"https://github.com/{full_name}/actions/runs/{run_id}",
            }


github_manager = GitHubSyncManager()
