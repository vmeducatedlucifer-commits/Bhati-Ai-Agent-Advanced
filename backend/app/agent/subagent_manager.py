"""SubAgent Manager — lifecycle management for spawned subagents.

Handles spawning, running, killing, pausing, and status tracking of subagents.
Each subagent runs as an independent asyncio task with its own context window,
but shares the parent's sandbox and permission scope.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.core.events import bus
from app.core.logging import get_logger
from app.core.utils import new_id, truncate
from app.db.models import SubAgent, Swarm, Thread, Project
from app.db.session import SessionLocal
from app.sandbox import sandboxes
from app.tools.base import ToolContext

log = get_logger("app.subagent_manager")

# ── Agent type definitions ──────────────────────────────────────────────────

AGENT_TYPES: dict[str, dict[str, Any]] = {
    "explorer": {
        "system_prompt": (
            "You are a codebase explorer. Search, read and summarise. Never modify files. "
            "Answer with concrete file paths and line numbers."
        ),
        "priority_default": "normal",
        "max_steps_default": 25,
        "tools_blocked": ["bash", "write_file", "edit_file", "delete_file"],
        "icon": "🔍",
        "color": "blue",
    },
    "coder": {
        "system_prompt": (
            "You are an implementation subagent. Make the requested change end to end, then "
            "report exactly what you changed."
        ),
        "priority_default": "high",
        "max_steps_default": 40,
        "tools_blocked": [],
        "icon": "💻",
        "color": "green",
    },
    "reviewer": {
        "system_prompt": (
            "You are a code reviewer. Inspect the diff and the surrounding code and report only "
            "real defects, each with a file path and a suggested fix."
        ),
        "priority_default": "high",
        "max_steps_default": 30,
        "tools_blocked": ["bash", "write_file", "edit_file", "delete_file"],
        "icon": "🔎",
        "color": "purple",
    },
    "researcher": {
        "system_prompt": (
            "You are a web researcher. Search, fetch and cross-check sources. Report findings "
            "with links and note anything you could not verify."
        ),
        "priority_default": "normal",
        "max_steps_default": 25,
        "tools_blocked": ["bash", "write_file", "edit_file", "delete_file"],
        "icon": "📚",
        "color": "orange",
    },
    "planner": {
        "system_prompt": (
            "You are a planning subagent. Analyze the task, break it into concrete steps, "
            "identify dependencies, and produce a detailed implementation plan with file paths "
            "and expected changes. Do NOT modify any files."
        ),
        "priority_default": "critical",
        "max_steps_default": 20,
        "tools_blocked": ["bash", "write_file", "edit_file", "delete_file"],
        "icon": "📋",
        "color": "yellow",
    },
    "tester": {
        "system_prompt": (
            "You are a testing subagent. Write and run tests for the specified code. "
            "Report test results, coverage gaps, and any failures with clear reproduction steps."
        ),
        "priority_default": "high",
        "max_steps_default": 35,
        "tools_blocked": [],
        "icon": "🧪",
        "color": "red",
    },
    "deployer": {
        "system_prompt": (
            "You are a deployment subagent. Handle build, packaging, and deployment tasks. "
            "Verify the deployment succeeded and report the endpoint or status."
        ),
        "priority_default": "critical",
        "max_steps_default": 30,
        "tools_blocked": [],
        "icon": "🚀",
        "color": "pink",
    },
    "monitor": {
        "system_prompt": (
            "You are a monitoring subagent. Check logs, metrics, health endpoints, and system "
            "status. Report anomalies, performance issues, and actionable recommendations."
        ),
        "priority_default": "normal",
        "max_steps_default": 20,
        "tools_blocked": ["write_file", "edit_file", "delete_file"],
        "icon": "📊",
        "color": "teal",
    },
    "coordinator": {
        "system_prompt": (
            "You are a coordinator subagent. You manage other subagents, distribute tasks, "
            "collect results, and synthesize a final report. Delegate work to specialized "
            "agents and track their progress."
        ),
        "priority_default": "critical",
        "max_steps_default": 50,
        "tools_blocked": [],
        "icon": "🎯",
        "color": "indigo",
    },
}

PRIORITY_LEVELS = {
    "critical": 0,
    "high": 1,
    "normal": 2,
    "low": 3,
    "background": 4,
}

PRIORITY_COLORS = {
    "critical": "red",
    "high": "orange",
    "normal": "blue",
    "low": "gray",
    "background": "slate",
}

# ── In-memory tracking ───────────────────────────────────────────────────────

class SubAgentRuntime:
    """Tracks in-flight subagent asyncio tasks for kill/pause support."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._cancel_events: dict[str, asyncio.Event] = {}
        self._pause_events: dict[str, asyncio.Event] = {}

    def register(self, agent_id: str, task: asyncio.Task, cancel_event: asyncio.Event) -> None:
        self._tasks[agent_id] = task
        self._cancel_events[agent_id] = cancel_event

    def unregister(self, agent_id: str) -> None:
        self._tasks.pop(agent_id, None)
        self._cancel_events.pop(agent_id, None)
        self._pause_events.pop(agent_id, None)

    def is_running(self, agent_id: str) -> bool:
        task = self._tasks.get(agent_id)
        return task is not None and not task.done()

    def cancel(self, agent_id: str) -> bool:
        event = self._cancel_events.get(agent_id)
        task = self._tasks.get(agent_id)
        if event is not None:
            event.set()
        if task is not None and not task.done():
            task.cancel()
        return event is not None or task is not None

    def pause(self, agent_id: str) -> bool:
        event = self._pause_events.get(agent_id)
        if event is None:
            event = asyncio.Event()
            event.set()
            self._pause_events[agent_id] = event
        event.clear()
        return True

    def resume(self, agent_id: str) -> bool:
        event = self._pause_events.get(agent_id)
        if event is None:
            return False
        event.set()
        return True

    def get_pause_event(self, agent_id: str) -> asyncio.Event:
        if agent_id not in self._pause_events:
            event = asyncio.Event()
            event.set()
            self._pause_events[agent_id] = event
        return self._pause_events[agent_id]

    def list_running(self) -> list[str]:
        return [aid for aid, task in self._tasks.items() if not task.done()]

    def cancel_all(self) -> int:
        count = 0
        for agent_id in list(self._tasks.keys()):
            if self.cancel(agent_id):
                count += 1
        return count


runtime = SubAgentRuntime()


# ── Core operations ─────────────────────────────────────────────────────────

async def spawn_subagent(
    *,
    thread_id: str,
    agent_type: str,
    name: str,
    prompt: str,
    priority: str = "normal",
    max_steps: int | None = None,
    tools_allowed: list[str] | None = None,
    tools_blocked: list[str] | None = None,
    parent_agent_id: str | None = None,
    swarm_id: str | None = None,
    parent_ctx: ToolContext | None = None,
) -> SubAgent:
    """Spawn a new subagent and start its execution loop."""
    if agent_type not in AGENT_TYPES:
        raise ValueError(f"Unknown agent_type: {agent_type}. Available: {', '.join(AGENT_TYPES.keys())}")

    type_config = AGENT_TYPES[agent_type]

    async with SessionLocal() as db:
        agent = SubAgent(
            thread_id=thread_id,
            parent_agent_id=parent_agent_id,
            swarm_id=swarm_id,
            name=name or f"{agent_type}-{new_id('')[:8]}",
            agent_type=agent_type,
            status="queued",
            priority=priority or type_config["priority_default"],
            prompt=prompt,
            system_extra=type_config["system_prompt"],
            max_steps=max_steps or type_config["max_steps_default"],
            tools_allowed=tools_allowed or [],
            tools_blocked=tools_blocked or type_config.get("tools_blocked", []),
        )
        db.add(agent)
        await db.commit()
        await db.refresh(agent)
        agent_id = agent.id

    topic = f"thread:{thread_id}"
    await bus.publish(topic, {
        "type": "subagent_spawned",
        "thread_id": thread_id,
        "agent_id": agent_id,
        "agent_type": agent_type,
        "name": name,
        "priority": priority,
        "swarm_id": swarm_id,
    })

    cancel_event = asyncio.Event()
    task = asyncio.create_task(
        _run_subagent_loop(
            agent_id=agent_id,
            thread_id=thread_id,
            parent_ctx=parent_ctx,
            cancel_event=cancel_event,
        )
    )
    runtime.register(agent_id, task, cancel_event)

    return agent


async def _run_subagent_loop(
    *,
    agent_id: str,
    thread_id: str,
    parent_ctx: ToolContext | None,
    cancel_event: asyncio.Event,
) -> None:
    """Execute a subagent's loop, updating status and result in DB."""
    from app.agent.loop import run_subagent, Interrupted  # lazy to avoid circular import

    topic = f"thread:{thread_id}"
    started_at = time.time()

    try:
        async with SessionLocal() as db:
            agent = await db.get(SubAgent, agent_id)
            if not agent:
                return
            agent.status = "spawning"
            agent.started_at = datetime.now(UTC)
            await db.commit()

        await bus.publish(topic, {
            "type": "subagent_status",
            "thread_id": thread_id,
            "agent_id": agent_id,
            "status": "spawning",
        })

        if cancel_event.is_set():
            raise Interrupted()

        async with SessionLocal() as db:
            agent = await db.get(SubAgent, agent_id)
            if agent:
                agent.status = "running"
                await db.commit()

        await bus.publish(topic, {
            "type": "subagent_status",
            "thread_id": thread_id,
            "agent_id": agent_id,
            "status": "running",
        })

        if parent_ctx is None:
            async with SessionLocal() as db:
                thread = await db.get(Thread, thread_id)
                project = await db.get(Project, thread.project_id) if thread else None
            if not thread or not project:
                raise RuntimeError(f"Thread {thread_id} or its project not found")

            sandbox = await sandboxes.get(thread_id, project.workspace_path)
            parent_ctx = ToolContext(
                thread_id=thread_id,
                project_id=project.id,
                workspace=project.workspace_path,
                sandbox=sandbox,
                emit=lambda type_, payload: bus.publish(topic, {"type": type_, "thread_id": thread_id, **(payload or {})}),
                tool_call_id=agent_id,
                depth=1,
                state={},
            )

        report = await run_subagent(
            parent=parent_ctx,
            system_extra=await _get_field(agent_id, "system_extra"),
            prompt=await _get_field(agent_id, "prompt"),
            max_steps=await _get_field(agent_id, "max_steps"),
            label=await _get_field(agent_id, "name"),
        )

        duration_ms = int((time.time() - started_at) * 1000)
        summary = report[:500] + "..." if len(report) > 500 else report

        async with SessionLocal() as db:
            agent = await db.get(SubAgent, agent_id)
            if agent:
                agent.status = "completed"
                agent.result = report
                agent.result_summary = summary
                agent.duration_ms = duration_ms
                agent.finished_at = datetime.now(UTC)
                agent.steps_completed = agent.max_steps
                await db.commit()

        await bus.publish(topic, {
            "type": "subagent_status",
            "thread_id": thread_id,
            "agent_id": agent_id,
            "status": "completed",
            "result_summary": summary,
            "duration_ms": duration_ms,
        })

    except asyncio.CancelledError:
        duration_ms = int((time.time() - started_at) * 1000)
        async with SessionLocal() as db:
            agent = await db.get(SubAgent, agent_id)
            if agent:
                agent.status = "killed"
                agent.error = "Agent was killed"
                agent.duration_ms = duration_ms
                agent.finished_at = datetime.now(UTC)
                await db.commit()

        await bus.publish(topic, {
            "type": "subagent_status",
            "thread_id": thread_id,
            "agent_id": agent_id,
            "status": "killed",
            "duration_ms": duration_ms,
        })

    except Interrupted:
        duration_ms = int((time.time() - started_at) * 1000)
        async with SessionLocal() as db:
            agent = await db.get(SubAgent, agent_id)
            if agent:
                agent.status = "killed"
                agent.error = "Agent was interrupted"
                agent.duration_ms = duration_ms
                agent.finished_at = datetime.now(UTC)
                await db.commit()

        await bus.publish(topic, {
            "type": "subagent_status",
            "thread_id": thread_id,
            "agent_id": agent_id,
            "status": "killed",
            "duration_ms": duration_ms,
        })

    except Exception as exc:
        log.exception("SubAgent %s failed", agent_id)
        duration_ms = int((time.time() - started_at) * 1000)
        async with SessionLocal() as db:
            agent = await db.get(SubAgent, agent_id)
            if agent:
                agent.status = "failed"
                agent.error = f"{type(exc).__name__}: {exc}"
                agent.duration_ms = duration_ms
                agent.finished_at = datetime.now(UTC)
                await db.commit()

        await bus.publish(topic, {
            "type": "subagent_status",
            "thread_id": thread_id,
            "agent_id": agent_id,
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
            "duration_ms": duration_ms,
        })

    finally:
        runtime.unregister(agent_id)


async def _get_field(agent_id: str, field: str) -> Any:
    async with SessionLocal() as db:
        agent = await db.get(SubAgent, agent_id)
        return getattr(agent, field, "") if agent else ""


async def kill_subagent(agent_id: str, force: bool = False) -> bool:
    """Kill a running subagent."""
    cancelled = runtime.cancel(agent_id)

    async with SessionLocal() as db:
        agent = await db.get(SubAgent, agent_id)
        if not agent:
            return False
        if agent.status in ("completed", "failed", "killed"):
            return False
        agent.status = "killed"
        agent.error = "Killed by user" if not force else "Force killed"
        agent.finished_at = datetime.now(UTC)
        await db.commit()
        thread_id = agent.thread_id

    await bus.publish(f"thread:{thread_id}", {
        "type": "subagent_status",
        "thread_id": thread_id,
        "agent_id": agent_id,
        "status": "killed",
    })

    return True


async def pause_subagent(agent_id: str) -> bool:
    """Pause a running subagent."""
    paused = runtime.pause(agent_id)
    if paused:
        async with SessionLocal() as db:
            agent = await db.get(SubAgent, agent_id)
            if agent and agent.status == "running":
                agent.status = "paused"
                await db.commit()

                await bus.publish(f"thread:{agent.thread_id}", {
                    "type": "subagent_status",
                    "thread_id": agent.thread_id,
                    "agent_id": agent_id,
                    "status": "paused",
                })
    return paused


async def resume_subagent(agent_id: str) -> bool:
    """Resume a paused subagent."""
    resumed = runtime.resume(agent_id)
    if resumed:
        async with SessionLocal() as db:
            agent = await db.get(SubAgent, agent_id)
            if agent and agent.status == "paused":
                agent.status = "running"
                await db.commit()

                await bus.publish(f"thread:{agent.thread_id}", {
                    "type": "subagent_status",
                    "thread_id": agent.thread_id,
                    "agent_id": agent_id,
                    "status": "running",
                })
    return resumed


async def get_subagent_status(agent_id: str) -> dict[str, Any] | None:
    """Get detailed status of a subagent."""
    async with SessionLocal() as db:
        agent = await db.get(SubAgent, agent_id)
        if not agent:
            return None
        return {
            "id": agent.id,
            "thread_id": agent.thread_id,
            "parent_agent_id": agent.parent_agent_id,
            "swarm_id": agent.swarm_id,
            "name": agent.name,
            "agent_type": agent.agent_type,
            "status": agent.status,
            "priority": agent.priority,
            "prompt": agent.prompt,
            "result": agent.result,
            "result_summary": agent.result_summary,
            "error": agent.error,
            "max_steps": agent.max_steps,
            "steps_completed": agent.steps_completed,
            "tools_allowed": agent.tools_allowed,
            "tools_blocked": agent.tools_blocked,
            "token_usage": agent.token_usage,
            "duration_ms": agent.duration_ms,
            "started_at": agent.started_at.isoformat() if agent.started_at else None,
            "finished_at": agent.finished_at.isoformat() if agent.finished_at else None,
            "meta": agent.meta,
            "is_live": runtime.is_running(agent_id),
        }


async def list_subagents(thread_id: str, status: str | None = None) -> list[dict[str, Any]]:
    """List all subagents for a thread."""
    async with SessionLocal() as db:
        query = select(SubAgent).where(SubAgent.thread_id == thread_id).order_by(SubAgent.created_at.desc())
        if status:
            query = query.where(SubAgent.status == status)
        agents = (await db.execute(query)).scalars().all()

        return [
            {
                "id": a.id,
                "name": a.name,
                "agent_type": a.agent_type,
                "status": a.status,
                "priority": a.priority,
                "result_summary": a.result_summary,
                "error": a.error,
                "duration_ms": a.duration_ms,
                "started_at": a.started_at.isoformat() if a.started_at else None,
                "finished_at": a.finished_at.isoformat() if a.finished_at else None,
                "swarm_id": a.swarm_id,
                "is_live": runtime.is_running(a.id),
            }
            for a in agents
        ]


async def kill_all_subagents(thread_id: str) -> int:
    """Kill all running subagents for a thread."""
    async with SessionLocal() as db:
        query = select(SubAgent).where(
            SubAgent.thread_id == thread_id,
            SubAgent.status.in_(["queued", "spawning", "running", "paused"])
        )
        agents = (await db.execute(query)).scalars().all()

    count = 0
    for agent in agents:
        if await kill_subagent(agent.id):
            count += 1
    return count
