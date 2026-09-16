"""Stall watchdog + loop repeat-guard: hangs must end visibly, never spin forever."""

from __future__ import annotations

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from app.agent.loop import AgentRunner
from app.llm import client as client_module
from app.llm.client import LLMClient
from app.llm.types import LLMError, ToolCall


def _chunk(payload: dict) -> bytes:
    return f"data: {json.dumps(payload)}\n\n".encode()


class _OkHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        body = (
            _chunk({"choices": [{"delta": {"content": "hello "}, "finish_reason": None}]})
            + _chunk({"choices": [{"delta": {"content": "world"}, "finish_reason": None}]})
            + _chunk({"choices": [{"delta": {}, "finish_reason": "stop"}]})
            + b"data: [DONE]\n\n"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _HangHandler(BaseHTTPRequestHandler):
    """Accepts the request, then sends nothing for 30s (stall simulator)."""

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
            import time as _time

            _time.sleep(30)
        except (BrokenPipeError, ConnectionResetError):
            pass


@pytest.fixture()
def ok_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _OkHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    server.shutdown()


@pytest.fixture()
def hang_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _HangHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    server.shutdown()


def test_pump_path_streams_normally(ok_server):
    async def go():
        client = LLMClient(base_url=ok_server, api_key="k", kind="openai", timeout=10)
        comp = await client.complete(model="m", messages=[{"role": "user", "content": "hi"}])
        return comp

    comp = asyncio.run(go())
    assert comp.content == "hello world"
    assert comp.finish_reason == "stop"


def test_stalled_stream_raises_visibly(hang_server, monkeypatch):
    monkeypatch.setattr(client_module, "STALL_TIMEOUT_S", 0.15)
    # Shrink backoffs so the test doesn't sleep through real retry delays.
    import asyncio as _asyncio

    real_sleep = _asyncio.sleep

    async def fast_sleep(delay, *args, **kwargs):
        await real_sleep(min(delay, 0.05), *args, **kwargs)

    monkeypatch.setattr(_asyncio, "sleep", fast_sleep)

    async def go():
        client = LLMClient(base_url=hang_server, api_key="k", kind="openai", timeout=10)
        await client.complete(model="m", messages=[{"role": "user", "content": "hi"}])

    with pytest.raises(LLMError, match="stalled"):
        asyncio.run(go())


def _runner() -> AgentRunner:
    thread = SimpleNamespace(id="thr_test", todos=[])
    project = SimpleNamespace(id="prj_test")
    return AgentRunner(thread=thread, project=project)  # type: ignore[arg-type]


def test_repeat_guard_trips_on_third_identical_call():
    runner = _runner()
    calls = [ToolCall(id="c1", name="read_file", arguments={"path": "a.py"})]
    assert runner._check_repeat(calls) is None
    assert runner._check_repeat(calls) is None
    msg = runner._check_repeat(calls)
    assert msg is not None and "3 times" in msg


def test_repeat_guard_resets_on_change():
    runner = _runner()
    a = [ToolCall(id="c1", name="read_file", arguments={"path": "a.py"})]
    b = [ToolCall(id="c2", name="read_file", arguments={"path": "b.py"})]
    assert runner._check_repeat(a) is None
    assert runner._check_repeat(a) is None
    assert runner._check_repeat(b) is None  # different args -> counter resets
    assert runner._check_repeat(b) is None
    assert runner._check_repeat(b) is not None
