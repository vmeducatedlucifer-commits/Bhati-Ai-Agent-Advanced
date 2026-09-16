"""Superserve backend: paths, exec mapping, error envelope, pool behavior.

Network is faked — these verify our mapping against the documented API
shapes (docs.superserve.ai), not the live service.
"""

from __future__ import annotations

import asyncio

from app.sandbox.base import ExecResult
from app.sandbox.superserve import (
    SuperserveClient,
    SuperserveError,
    SuperservePool,
    SuperserveSandbox,
    _api_error,
)


class FakeClient(SuperserveClient):
    def __init__(self):
        super().__init__("ss_live_test")
        self.calls: list = []
        self.script: list = []

    async def _request(self, method, url, *, headers, **kwargs):
        self.calls.append((method, url))
        action = self.script.pop(0)
        if isinstance(action, Exception):
            raise action
        return action


def test_api_error_envelope():
    err = _api_error(
        429, {"error": {"code": "too_many_sandboxes", "message": "quota hit"}}, "POST x"
    )
    assert err.code == "too_many_sandboxes"
    assert err.status == 429
    assert "quota" in str(err)


def test_path_mapping(tmp_path):
    client = FakeClient()
    box = SuperserveSandbox("thr1", str(tmp_path), client)
    assert box._abs("a/b.txt") == "/home/user/bhati/a/b.txt"
    assert box._abs("") == "/home/user/bhati"
    assert box._rel("/home/user/bhati/a/b.txt") == "a/b.txt"


def test_exec_maps_result_and_refreshes_token():
    async def run():
        client = FakeClient()
        client.script = [
            SuperserveError("paused", code="paused", status=503),
            {"stdout": "hi\n", "stderr": "", "exit_code": 0},
        ]

        async def fake_activate(box_id):
            return {"access_token": "tok-fresh"}

        client.activate = fake_activate
        data = await client.exec("box1", "tok-old", "echo hi")
        assert data["stdout"] == "hi\n"
        assert data["_access_token"] == "tok-fresh"
        assert data["_duration_ms"] >= 0

    asyncio.run(run())


def test_exec_truncated_note():
    async def run():
        client = FakeClient()
        client.script = [{"stdout": "x", "stderr": "", "exit_code": 0, "truncated": True}]
        box = SuperserveSandbox("thr1", "/tmp", client, box_id="box1", access_token="t")
        result = await box.exec("echo hi")
        assert isinstance(result, ExecResult)
        assert result.exit_code == 0
        assert "truncated" in result.stderr

    asyncio.run(run())


def test_delete_refuses_root():
    async def run():
        client = FakeClient()
        box = SuperserveSandbox("thr1", "/tmp", client, box_id="box1", access_token="t")
        try:
            await box.delete("")
            raise AssertionError("should have refused")
        except SuperserveError as exc:
            assert exc.code == "bad_path"

    asyncio.run(run())


def test_pool_quota_flag_and_status():
    async def run():
        client = FakeClient()
        pool = SuperservePool(client=client, size=5)
        client.script = [SuperserveError("full", code="too_many_sandboxes", status=429)]
        await pool.maintain()
        assert pool.quota_exhausted is True
        assert pool.status()["warm"] == 0
        assert pool.status()["size"] == 5

    asyncio.run(run())


def test_pool_acquire_healthy_first():
    async def run():
        client = FakeClient()

        async def fake_get(box_id):
            return {"status": "active" if box_id == "good" else "deleted"}

        async def fake_delete(box_id):
            return None

        client.get = fake_get
        client.delete = fake_delete
        from app.sandbox.superserve import PooledBox

        pool = SuperservePool(client=client, size=5)
        pool.boxes = [PooledBox(id="bad", access_token="t"), PooledBox(id="good", access_token="t")]
        box = await pool.acquire()
        assert box is not None and box.id == "good"

    asyncio.run(run())
