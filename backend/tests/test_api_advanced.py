"""API smoke tests for advanced endpoints: share, fork/truncate, jobs,
stats, snapshots, clone, storage, audit. Catches route-registration crashes."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def project(client):
    response = client.post("/api/v1/projects", json={"name": "Smoke Project"})
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture(scope="module")
def thread(client, project):
    response = client.post(
        "/api/v1/threads", json={"project_id": project["id"], "title": "Smoke Chat"}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_share_lifecycle(client, thread):
    created = client.post(f"/api/v1/threads/{thread['id']}/share", json={"role": "viewer"})
    assert created.status_code == 201, created.text
    token = created.json()["token"]

    listed = client.get(f"/api/v1/threads/{thread['id']}/shares")
    assert listed.status_code == 200
    assert any(s["token"] == token for s in listed.json())

    public = client.get(f"/api/v1/share/{token}")
    assert public.status_code == 200, public.text
    assert public.json()["thread"]["id"] == thread["id"]

    revoked = client.delete(f"/api/v1/share/{token}")
    assert revoked.status_code == 200

    gone = client.get(f"/api/v1/share/{token}")
    assert gone.status_code == 404


def test_fork_copies_thread(client, thread):
    response = client.post(
        f"/api/v1/threads/{thread['id']}/fork", json={"title": "Smoke Branch"}
    )
    assert response.status_code == 201, response.text
    fork = response.json()
    assert fork["id"] != thread["id"]
    assert fork["project_id"] == thread["project_id"]

    messages = client.get(f"/api/v1/threads/{fork['id']}/messages")
    assert messages.status_code == 200


def test_truncate_missing_message_is_404(client, thread):
    response = client.post(
        f"/api/v1/threads/{thread['id']}/truncate", json={"from_message_id": "msg_nope"}
    )
    assert response.status_code == 404


def test_truncate_real_message(client, thread):
    import asyncio

    from app.core.utils import new_id
    from app.db.models import Message
    from app.db.session import SessionLocal

    async def _insert() -> str:
        async with SessionLocal() as db:
            msg = Message(
                id=new_id("msg"),
                thread_id=thread["id"],
                position=0,
                role="user",
                content="hello",
                raw={"role": "user", "content": "hello"},
            )
            db.add(msg)
            await db.commit()
            return msg.id

    message_id = asyncio.run(_insert())
    response = client.post(
        f"/api/v1/threads/{thread['id']}/truncate", json={"from_message_id": message_id}
    )
    assert response.status_code == 200, response.text

    messages = client.get(f"/api/v1/threads/{thread['id']}/messages")
    assert messages.status_code == 200
    assert all(m["id"] != message_id for m in messages.json())


def test_jobs_crud(client, project):
    created = client.post(
        "/api/v1/jobs",
        json={
            "name": "Smoke job",
            "project_id": project["id"],
            "prompt": "Say hi",
            "interval_minutes": 60,
        },
    )
    assert created.status_code == 201, created.text
    job = created.json()

    listed = client.get(f"/api/v1/jobs?project_id={project['id']}")
    assert listed.status_code == 200
    assert any(j["id"] == job["id"] for j in listed.json())

    patched = client.patch(f"/api/v1/jobs/{job['id']}", json={"enabled": False})
    assert patched.status_code == 200
    assert patched.json()["enabled"] is False

    deleted = client.delete(f"/api/v1/jobs/{job['id']}")
    assert deleted.status_code == 200


def test_stats_endpoints(client):
    for path in ("/api/v1/stats/overview", "/api/v1/stats/by-model", "/api/v1/stats/daily"):
        response = client.get(path)
        assert response.status_code == 200, path


def test_snapshot_lifecycle(client, project):
    created = client.post(
        f"/api/v1/projects/{project['id']}/snapshots", json={"label": "smoke"}
    )
    assert created.status_code == 201, created.text
    name = created.json()["name"]

    listed = client.get(f"/api/v1/projects/{project['id']}/snapshots")
    assert listed.status_code == 200
    assert any(s["name"] == name for s in listed.json())

    restored = client.post(f"/api/v1/projects/{project['id']}/snapshots/{name}/restore")
    assert restored.status_code == 200, restored.text

    deleted = client.delete(f"/api/v1/projects/{project['id']}/snapshots/{name}")
    assert deleted.status_code == 200


def test_storage_and_clone(client, project):
    storage = client.get(f"/api/v1/projects/{project['id']}/storage")
    assert storage.status_code == 200, storage.text
    assert storage.json()["bytes"] >= 0

    cloned = client.post(
        f"/api/v1/projects/{project['id']}/clone", json={"name": "Smoke Clone"}
    )
    assert cloned.status_code == 201, cloned.text
    assert cloned.json()["id"] != project["id"]


def test_audit_lists(client):
    response = client.get("/api/v1/audit?limit=10")
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_artifact_comments(client, thread):
    import asyncio

    from app.core.utils import new_id
    from app.db.models import Artifact
    from app.db.session import SessionLocal

    async def _insert() -> str:
        async with SessionLocal() as db:
            artifact = Artifact(
                id=new_id("art"),
                thread_id=thread["id"],
                title="Smoke artifact",
                kind="markdown",
                content="# hi",
            )
            db.add(artifact)
            await db.commit()
            return artifact.id

    artifact_id = asyncio.run(_insert())
    created = client.post(
        f"/api/v1/threads/{thread['id']}/artifacts/{artifact_id}/comments",
        json={"content": "Nice work", "author": "tester"},
    )
    assert created.status_code == 201, created.text

    listed = client.get(f"/api/v1/threads/{thread['id']}/artifacts/{artifact_id}/comments")
    assert listed.status_code == 200
    assert any(c["content"] == "Nice work" for c in listed.json())


def test_logout_wipes_site_data(client):
    resp = client.post("/api/v1/auth/logout")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"logged_out": True}
    assert resp.headers.get("clear-site-data") == '"cache", "storage"'


def test_api_responses_are_not_cached(client, thread):
    resp = client.get(f"/api/v1/threads/{thread['id']}/messages")
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("cache-control") == "no-store, no-cache, must-revalidate"
    assert resp.headers.get("strict-transport-security", "").startswith("max-age=")


def test_log_redaction_strips_secrets():
    from app.core.logging import _redact

    line = '127.0.0.1 - "GET /api/v1/threads/t/stream?after=0&token=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJyYXdhbCJ9.sig HTTP/1.1" 200'
    redacted = _redact(line)
    assert "eyJhbGciOiJIUzI1NiJ9" not in redacted
    assert "token=[REDACTED]" in redacted
    assert _redact("preview?ticket=1789.abc123&x=1") == "preview?ticket=[REDACTED]&x=1"


def test_sandbox_ping_is_keepalive_only(client, thread):
    # Ping touches an existing box but never creates one: a fresh thread has
    # no box, so status stays not_started (panel shows live state, no spawn).
    first = client.post(f"/api/v1/threads/{thread['id']}/sandbox/ping")
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "not_started"

    started = client.post(f"/api/v1/threads/{thread['id']}/sandbox/start")
    assert started.status_code == 200, started.text

    second = client.post(f"/api/v1/threads/{thread['id']}/sandbox/ping")
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["status"] == "running"
    assert body["backend"]
