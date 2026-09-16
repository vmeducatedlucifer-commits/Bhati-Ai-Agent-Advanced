import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.api.v1.browser as browser_api
from app.browser import browsers
from app.main import app


class FakeDb:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


async def fake_thread_and_project(_db, _thread_id):
    return SimpleNamespace(id="stream-thread"), SimpleNamespace(workspace_path="/tmp")


async def main() -> None:
    original_db = browser_api.SessionLocal
    original_lookup = browser_api.get_thread_and_project
    browser_api.SessionLocal = FakeDb
    browser_api.get_thread_and_project = fake_thread_and_project
    try:
        with TestClient(app) as client:
            with client.websocket_connect("/api/v1/threads/stream-thread/browser/stream") as socket:
                ready = socket.receive_json()
                assert ready["type"] == "ready"
                frame = socket.receive_json()
                assert frame["type"] == "frame"
                assert frame["mime"] == "image/jpeg"
                assert frame["image_base64"]
                socket.send_json({"type": "click", "x": 50, "y": 50})
                messages = [socket.receive_json() for _ in range(3)]
                assert any(item.get("type") == "ack" for item in messages)
        print("browser websocket stream smoke test passed")
    finally:
        await browsers.close("stream-thread")
        browser_api.SessionLocal = original_db
        browser_api.get_thread_and_project = original_lookup


if __name__ == "__main__":
    asyncio.run(main())
