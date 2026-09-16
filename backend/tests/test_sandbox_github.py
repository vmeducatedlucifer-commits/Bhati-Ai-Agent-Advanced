"""GitHub Actions backend: run matching, artifact parsing, Contents files.

The GitHub API is faked — these verify our mapping (run-name marker,
result artifact, base64 Contents flow), not the live service.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import zipfile

from app.sandbox.github_actions import (
    WORKFLOW_YAML,
    GitHubActionsSandbox,
    find_run,
    parse_result_artifact,
)


def _zip_result(payload: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("bhati-result-abc123/bhati-result.json", json.dumps(payload))
    return buf.getvalue()


class FakeGitHub:
    def __init__(self):
        self.requests: list = []
        self.last_run_id = "abc123"
        self.contents: dict = {}
        self.artifact_zip = _zip_result({"stdout": "hi\n", "stderr": "", "exit_code": 0})

    async def request(self, method, path, **kwargs):
        self.requests.append((method, path))
        if path.endswith("/dispatches"):
            self.last_run_id = (kwargs.get("json") or {}).get("inputs", {}).get("run_id", "abc123")
            return {}
        if "contents/.github/workflows/sandbox-runner.yml" in path:
            if method == "GET":
                raise ValueError("not found")
            return {"content": {"sha": "new"}}
        if "/actions/workflows/" in path and path.endswith("/runs"):
            return {"workflow_runs": [{
                "id": 99, "display_title": f"bhati-{self.last_run_id}",
                "status": "completed", "conclusion": "success",
            }]}
        if "/actions/runs/" in path and path.endswith("/artifacts"):
            return {"artifacts": [{"id": 7, "name": "bhati-result-abc123"}]}
        if path.endswith("/contents") or "/contents/" in path:
            key = path.split("/contents", 1)[1].strip("/")
            if method == "GET":
                if key in self.contents:
                    body, sha = self.contents[key]
                    return {"type": "file", "sha": sha,
                            "content": base64.b64encode(body).decode()}
                raise ValueError("not found")
            if method == "PUT":
                self.contents[key] = (base64.b64decode(kwargs["json"]["content"]), "sha2")
                return {}
            if method == "DELETE":
                self.contents.pop(key, None)
                return {}
        if path.startswith("/repos/") and method == "GET":
            return {"default_branch": "main"}
        raise AssertionError(f"unexpected {method} {path}")

    async def request_bytes(self, method, path, **kwargs):
        self.requests.append((method, path))
        return self.artifact_zip

    async def whoami(self):
        return {"login": "tester"}


def test_find_run_matches_marker():
    runs = [
        {"id": 1, "display_title": "other workflow", "status": "completed"},
        {"id": 2, "display_title": "bhati-abc123", "status": "in_progress"},
    ]
    assert find_run(runs, "abc123")["id"] == 2
    assert find_run(runs, "zzz") is None


def test_parse_result_artifact():
    data = parse_result_artifact(_zip_result({"stdout": "ok", "stderr": "", "exit_code": 0}))
    assert data == {"stdout": "ok", "stderr": "", "exit_code": 0}


def test_workflow_yaml_has_result_channel():
    assert 'run-name: "bhati-${{ inputs.run_id }}"' in WORKFLOW_YAML
    assert "upload-artifact" in WORKFLOW_YAML
    assert "bhati-result.json" in WORKFLOW_YAML


def test_exec_round_trip():
    async def run():
        client = FakeGitHub()
        box = GitHubActionsSandbox("thr1", "/tmp/ws", client, "tester/demo")
        await box.start()
        assert any("sandbox-runner.yml" in p for _, p in client.requests)
        result = await box.exec("echo hi", timeout=120)
        assert result.exit_code == 0
        assert result.stdout == "hi\n"

    asyncio.run(run())


def test_files_round_trip():
    async def run():
        client = FakeGitHub()
        box = GitHubActionsSandbox("thr1", "/tmp/ws", client, "tester/demo")
        assert await box.write_file("a.txt", "hello") == 5
        assert await box.read_file("a.txt") == "hello"
        assert await box.exists("a.txt") is True
        assert await box.exists("nope.txt") is False
        await box.delete("a.txt")
        assert await box.exists("a.txt") is False

    asyncio.run(run())


def test_delete_refuses_root():
    async def run():
        client = FakeGitHub()
        box = GitHubActionsSandbox("thr1", "/tmp/ws", client, "tester/demo")
        try:
            await box.delete("")
            raise AssertionError("should have refused")
        except ValueError:
            pass

    asyncio.run(run())
