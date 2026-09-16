"""Live Playwright browser session endpoints."""

from __future__ import annotations

import asyncio
import json
from contextlib import suppress

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from app.api.deps import DB, Auth, get_thread_and_project, require_ws_auth
from app.browser import BrowserUnavailable, browsers
from app.db.session import SessionLocal

router = APIRouter(prefix="/threads", tags=["browser"])


class NavigateBody(BaseModel):
    url: str = Field(min_length=8, max_length=4096)


class ClickBody(BaseModel):
    x: int = Field(ge=0, le=4096)
    y: int = Field(ge=0, le=4096)
    button: str = Field(default="left", pattern="^(left|right|middle)$")
    double: bool = False


class TypeBody(BaseModel):
    text: str = Field(max_length=20_000)
    selector: str = Field(default="", max_length=500)
    clear: bool = True


class PressBody(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    selector: str = Field(default="", max_length=500)


class ScrollBody(BaseModel):
    delta_x: int = Field(default=0, ge=-10_000, le=10_000)
    delta_y: int = Field(default=700, ge=-10_000, le=10_000)


async def _session(thread_id: str, db: DB):
    _thread, project = await get_thread_and_project(db, thread_id)
    try:
        session = await browsers.get(thread_id, project.workspace_path)
        await session.ensure()
        return session
    except BrowserUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/{thread_id}/browser")
async def browser_info(thread_id: str, db: DB, _: Auth):
    _thread, project = await get_thread_and_project(db, thread_id)
    session = await browsers.peek(thread_id)
    if not session or not session.page or session.page.is_closed():
        return {"status": "not_started", "url": "", "title": "", "started_at": None}
    return {
        "status": "running",
        "url": session.page.url,
        "title": await session.page.title(),
        "started_at": session.started_at,
        "workspace": project.workspace_path,
    }


@router.post("/{thread_id}/browser/start")
async def browser_start(thread_id: str, db: DB, _: Auth):
    _thread, project = await get_thread_and_project(db, thread_id)
    try:
        session = await browsers.get(thread_id, project.workspace_path)
        await session.start()
        return {
            "status": "running",
            "url": session.page.url if session.page else "",
            "title": await session.page.title() if session.page else "",
            "started_at": session.started_at,
        }
    except BrowserUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/{thread_id}/browser/navigate")
async def browser_navigate(thread_id: str, body: NavigateBody, db: DB, _: Auth):
    session = await _session(thread_id, db)
    try:
        return {"status": "running", **(await session.navigate(body.url))}
    except (BrowserUnavailable, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"browser navigation failed: {exc}") from exc


@router.post("/{thread_id}/browser/click")
async def browser_click(thread_id: str, body: ClickBody, db: DB, _: Auth):
    session = await _session(thread_id, db)
    try:
        return await session.mouse("dblclick" if body.double else "click", body.x, body.y, body.button)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{thread_id}/browser/type")
async def browser_type(thread_id: str, body: TypeBody, db: DB, _: Auth):
    session = await _session(thread_id, db)
    try:
        if body.selector:
            return await session.type_text(body.selector, body.text, body.clear)
        page = await session.ensure()
        async with session.lock:
            await page.keyboard.type(body.text)
            return {"characters": len(body.text), "url": page.url}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{thread_id}/browser/press")
async def browser_press(thread_id: str, body: PressBody, db: DB, _: Auth):
    session = await _session(thread_id, db)
    try:
        return await session.press(body.key, body.selector or None)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{thread_id}/browser/scroll")
async def browser_scroll(thread_id: str, body: ScrollBody, db: DB, _: Auth):
    session = await _session(thread_id, db)
    try:
        return await session.scroll(body.delta_x, body.delta_y)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{thread_id}/browser/screenshot")
async def browser_screenshot(thread_id: str, db: DB, _: Auth, full_page: bool = False):
    session = await _session(thread_id, db)
    try:
        snapshot = await session.screenshot(full_page=full_page)
        return {
            "status": "running",
            "url": snapshot.url,
            "title": snapshot.title,
            "image_base64": snapshot.image_base64,
            "width": snapshot.width,
            "height": snapshot.height,
            "captured_at": snapshot.captured_at,
        }
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{thread_id}/browser")
async def browser_stop(thread_id: str, db: DB, _: Auth):
    await get_thread_and_project(db, thread_id)
    await browsers.close(thread_id)
    return {"stopped": thread_id}


@router.websocket("/{thread_id}/browser/stream")
async def browser_stream(websocket: WebSocket, thread_id: str):
    """VNC-style realtime browser stream with a bidirectional input channel.

    Frames are compact JPEG JSON payloads so the same transport works in browsers
    without a WebRTC media server. The message contract is intentionally simple
    enough to be upgraded to WebRTC later without changing browser actions.
    """
    await require_ws_auth(websocket)
    await websocket.accept()
    try:
        async with SessionLocal() as db:
            _thread, project = await get_thread_and_project(db, thread_id)
        session = await browsers.get(thread_id, project.workspace_path)
        await session.ensure()
        await websocket.send_json({"type": "ready", "url": session.page.url, "title": await session.page.title()})
    except Exception as exc:
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close()
        return

    stopped = asyncio.Event()

    async def send_frames() -> None:
        last_url = ""
        while not stopped.is_set():
            try:
                frame = await session.frame()
                await websocket.send_json({
                    "type": "frame",
                    "url": frame.url,
                    "title": frame.title,
                    "image_base64": frame.image_base64,
                    "mime": "image/jpeg",
                    "width": frame.width,
                    "height": frame.height,
                    "captured_at": frame.captured_at,
                })
                if frame.url != last_url:
                    await websocket.send_json({"type": "navigation", "url": frame.url, "title": frame.title})
                    last_url = frame.url
            except Exception as exc:
                await websocket.send_json({"type": "error", "message": str(exc)})
                return
            await asyncio.sleep(0.25)

    frames = asyncio.create_task(send_frames())
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "invalid JSON command"})
                continue
            kind = message.get("type")
            try:
                if kind == "navigate":
                    result = await session.navigate(str(message.get("url", "")))
                elif kind == "click":
                    result = await session.mouse("dblclick" if message.get("double") else "click", float(message["x"]), float(message["y"]), str(message.get("button", "left")))
                elif kind == "type":
                    text = str(message.get("text", ""))
                    page = await session.ensure()
                    async with session.lock:
                        await page.keyboard.type(text)
                    result = {"characters": len(text), "url": page.url}
                elif kind == "press":
                    result = await session.press(str(message.get("key", "")))
                elif kind == "scroll":
                    result = await session.scroll(float(message.get("delta_x", 0)), float(message.get("delta_y", 700)))
                elif kind == "ping":
                    await websocket.send_json({"type": "pong"})
                    continue
                elif kind == "close":
                    break
                else:
                    await websocket.send_json({"type": "error", "message": f"unknown browser command: {kind}"})
                    continue
                await websocket.send_json({"type": "ack", "action": kind, "result": result})
            except Exception as exc:
                await websocket.send_json({"type": "action_error", "action": kind, "message": str(exc)})
    except WebSocketDisconnect:
        pass
    finally:
        stopped.set()
        frames.cancel()
        with suppress(asyncio.CancelledError):
            await frames
