"""Interactive terminal over WebSocket, plus sandbox lifecycle control."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.api.deps import DB, Auth, get_thread_and_project, require_ws_auth
from app.core.logging import get_logger
from app.db.session import SessionLocal
from app.sandbox import sandboxes

log = get_logger("app.api.terminal")
router = APIRouter(prefix="/threads", tags=["sandbox"])


class ExecBody(BaseModel):
    command: str
    cwd: str = ""
    timeout: int = 120


@router.get("/{thread_id}/sandbox")
async def sandbox_info(thread_id: str, db: DB, _: Auth):
    thread, project = await get_thread_and_project(db, thread_id)
    box = await sandboxes.peek(thread_id)
    if box is None:
        return {
            "status": "not_started",
            "backend": await sandboxes.backend(),
            "workspace": project.workspace_path,
        }
    info = await box.info()
    return {
        "id": info.id,
        "status": info.status,
        "backend": info.backend,
        "workspace": info.workspace,
        "image": info.image,
        "started_at": info.started_at,
        "detail": info.detail,
    }


@router.post("/{thread_id}/sandbox/start")
async def sandbox_start(thread_id: str, db: DB, _: Auth):
    thread, project = await get_thread_and_project(db, thread_id)
    box = await sandboxes.get(thread_id, project.workspace_path)
    info = await box.info()
    return {"id": info.id, "status": info.status, "backend": info.backend, "image": info.image}


@router.post("/{thread_id}/sandbox/restart")
async def sandbox_restart(thread_id: str, db: DB, _: Auth):
    thread, project = await get_thread_and_project(db, thread_id)
    box = await sandboxes.restart(thread_id, project.workspace_path)
    info = await box.info()
    return {"id": info.id, "status": info.status, "backend": info.backend}


@router.post("/{thread_id}/sandbox/stop")
async def sandbox_stop(thread_id: str, _: Auth):
    await sandboxes.release(thread_id)
    return {"stopped": thread_id}


@router.post("/{thread_id}/sandbox/ping")
async def sandbox_ping(thread_id: str, db: DB, _: Auth):
    """Lightweight keepalive for an open Computer panel.

    Only touches an EXISTING box (never creates one), so closing the UI still
    lets the idle reaper collect the sandbox. Returns live status so the panel
    always shows the current state on open.
    """
    await get_thread_and_project(db, thread_id)
    sandboxes.touch(thread_id)
    box = await sandboxes.peek(thread_id)
    if box is None:
        return {"status": "not_started", "backend": await sandboxes.backend()}
    info = await box.info()
    return {"id": info.id, "status": info.status, "backend": info.backend}


@router.post("/{thread_id}/sandbox/exec")
async def sandbox_exec(thread_id: str, body: ExecBody, db: DB, _: Auth):
    thread, project = await get_thread_and_project(db, thread_id)
    box = await sandboxes.get(thread_id, project.workspace_path)
    result = await box.exec(body.command, cwd=body.cwd or None, timeout=body.timeout)
    return {
        "exit_code": result.exit_code,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "duration_ms": result.duration_ms,
        "timed_out": result.timed_out,
    }


@router.websocket("/{thread_id}/terminal")
async def terminal(websocket: WebSocket, thread_id: str):
    """Line-oriented shell. The client sends {"type":"run","command":"..."}."""
    await require_ws_auth(websocket)
    await websocket.accept()

    async with SessionLocal() as db:
        try:
            thread, project = await get_thread_and_project(db, thread_id)
        except Exception as exc:
            await websocket.send_json({"type": "error", "message": str(exc)})
            await websocket.close()
            return

    box = await sandboxes.get(thread_id, project.workspace_path)
    info = await box.info()
    cwd = ""
    await websocket.send_json(
        {"type": "ready", "backend": info.backend, "workspace": info.workspace, "image": info.image}
    )

    current: asyncio.Task | None = None

    async def run_command(command: str, timeout: int) -> None:
        nonlocal cwd
        stripped = command.strip()
        if stripped.startswith("cd "):
            target = stripped[3:].strip()
            cwd = "" if target in ("", "~", "/") else (target if target.startswith("/") else f"{cwd}/{target}".strip("/"))
            probe = await box.exec("pwd", cwd=cwd or None, timeout=15)
            await websocket.send_json({"type": "output", "chunk": probe.stdout})
            await websocket.send_json({"type": "end", "exit_code": probe.exit_code, "cwd": cwd})
            return
        exit_code = 0
        try:
            async for chunk in box.exec_stream(command, cwd=cwd or None, timeout=timeout):
                await websocket.send_json({"type": "output", "chunk": chunk})
        except Exception as exc:
            exit_code = 1
            await websocket.send_json({"type": "output", "chunk": f"\n[error] {exc}\n"})
        await websocket.send_json({"type": "end", "exit_code": exit_code, "cwd": cwd})

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                message = {"type": "run", "command": raw}

            kind = message.get("type")
            if kind == "run":
                sandboxes.touch(thread_id)
                if current and not current.done():
                    await websocket.send_json({"type": "output", "chunk": "\n[busy]\n"})
                    continue
                current = asyncio.create_task(
                    run_command(message.get("command", ""), int(message.get("timeout", 300)))
                )
            elif kind == "interrupt":
                if current and not current.done():
                    current.cancel()
                    await websocket.send_json({"type": "output", "chunk": "^C\n"})
                    await websocket.send_json({"type": "end", "exit_code": 130, "cwd": cwd})
            elif kind == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover
        log.warning("terminal socket error on %s: %s", thread_id, exc)
    finally:
        if current and not current.done():
            current.cancel()
