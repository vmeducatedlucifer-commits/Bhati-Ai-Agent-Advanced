"""Swarm Manager — deploy and coordinate groups of subagents.

Strategies: parallel, sequential, map_reduce, hierarchical
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.agent.subagent_manager import (
    AGENT_TYPES,
    PRIORITY_LEVELS,
    spawn_subagent,
    kill_subagent,
    get_subagent_status,
    runtime,
)
from app.core.events import bus
from app.core.logging import get_logger
from app.core.utils import new_id, truncate
from app.db.models import SubAgent, Swarm, Thread, Project
from app.db.session import SessionLocal
from app.tools.base import ToolContext

log = get_logger("app.swarm_manager")


async def deploy_swarm(
    *,
    thread_id: str,
    name: str,
    prompt: str,
    strategy: str = "parallel",
    agent_configs: list[dict[str, Any]] | None = None,
    agent_count: int = 3,
    agent_type: str = "coder",
    priority: str = "normal",
    max_steps: int = 25,
    parent_ctx: ToolContext | None = None,
) -> Swarm:
    """Deploy a swarm of subagents for a coordinated task."""

    if strategy not in ("parallel", "sequential", "map_reduce", "hierarchical"):
        raise ValueError(f"Unknown strategy: {strategy}")

    async with SessionLocal() as db:
        swarm = Swarm(
            thread_id=thread_id,
            name=name or f"swarm-{new_id('')[:8]}",
            strategy=strategy,
            status="deploying",
            prompt=prompt,
            agent_count=agent_count,
        )
        db.add(swarm)
        await db.commit()
        await db.refresh(swarm)
        swarm_id = swarm.id

    topic = f"thread:{thread_id}"
    await bus.publish(topic, {
        "type": "swarm_deployed",
        "thread_id": thread_id,
        "swarm_id": swarm_id,
        "name": name,
        "strategy": strategy,
        "agent_count": agent_count,
    })

    task = asyncio.create_task(
        _run_swarm(
            swarm_id=swarm_id,
            thread_id=thread_id,
            prompt=prompt,
            strategy=strategy,
            agent_configs=agent_configs,
            agent_count=agent_count,
            agent_type=agent_type,
            priority=priority,
            max_steps=max_steps,
            parent_ctx=parent_ctx,
        )
    )

    return swarm


async def _run_swarm(
    *,
    swarm_id: str,
    thread_id: str,
    prompt: str,
    strategy: str,
    agent_configs: list[dict[str, Any]] | None,
    agent_count: int,
    agent_type: str,
    priority: str,
    max_steps: int,
    parent_ctx: ToolContext | None,
) -> None:
    topic = f"thread:{thread_id}"
    started_at = time.time()

    try:
        async with SessionLocal() as db:
            swarm = await db.get(Swarm, swarm_id)
            if swarm:
                swarm.status = "running"
                await db.commit()

        await bus.publish(topic, {
            "type": "swarm_status",
            "thread_id": thread_id,
            "swarm_id": swarm_id,
            "status": "running",
        })

        if strategy == "parallel":
            result = await _run_parallel(swarm_id, thread_id, prompt, agent_configs, agent_count, agent_type, priority, max_steps, parent_ctx)
        elif strategy == "sequential":
            result = await _run_sequential(swarm_id, thread_id, prompt, agent_configs, agent_count, agent_type, priority, max_steps, parent_ctx)
        elif strategy == "map_reduce":
            result = await _run_map_reduce(swarm_id, thread_id, prompt, agent_configs, agent_count, agent_type, priority, max_steps, parent_ctx)
        elif strategy == "hierarchical":
            result = await _run_hierarchical(swarm_id, thread_id, prompt, agent_configs, agent_count, agent_type, priority, max_steps, parent_ctx)
        else:
            result = f"Unknown strategy: {strategy}"

        duration_ms = int((time.time() - started_at) * 1000)
        async with SessionLocal() as db:
            swarm = await db.get(Swarm, swarm_id)
            if swarm:
                swarm.status = "completed"
                swarm.result = result
                swarm.meta["duration_ms"] = duration_ms
                await db.commit()

        await bus.publish(topic, {
            "type": "swarm_status",
            "thread_id": thread_id,
            "swarm_id": swarm_id,
            "status": "completed",
            "result_summary": result[:500] if result else "",
            "duration_ms": duration_ms,
        })

    except asyncio.CancelledError:
        async with SessionLocal() as db:
            swarm = await db.get(Swarm, swarm_id)
            if swarm:
                swarm.status = "killed"
                await db.commit()

        await bus.publish(topic, {"type": "swarm_status", "thread_id": thread_id, "swarm_id": swarm_id, "status": "killed"})

    except Exception as exc:
        log.exception("Swarm %s failed", swarm_id)
        async with SessionLocal() as db:
            swarm = await db.get(Swarm, swarm_id)
            if swarm:
                swarm.status = "failed"
                swarm.result = f"Error: {exc}"
                await db.commit()

        await bus.publish(topic, {"type": "swarm_status", "thread_id": thread_id, "swarm_id": swarm_id, "status": "failed", "error": str(exc)})


async def _run_parallel(swarm_id, thread_id, prompt, agent_configs, agent_count, agent_type, priority, max_steps, parent_ctx) -> str:
    configs = agent_configs or [
        {"agent_type": agent_type, "name": f"worker-{i+1}", "prompt": prompt}
        for i in range(agent_count)
    ]

    agents = []
    for cfg in configs:
        agent = await spawn_subagent(
            thread_id=thread_id,
            agent_type=cfg.get("agent_type", agent_type),
            name=cfg.get("name", f"worker-{len(agents)+1}"),
            prompt=cfg.get("prompt", prompt),
            priority=cfg.get("priority", priority),
            max_steps=cfg.get("max_steps", max_steps),
            swarm_id=swarm_id,
            parent_ctx=parent_ctx,
        )
        agents.append(agent)

    results = []
    for agent in agents:
        for _ in range(300):
            status = await get_subagent_status(agent.id)
            if status and status["status"] in ("completed", "failed", "killed"):
                results.append(status)
                break
            await asyncio.sleep(1)

    return _merge_results(results, "parallel")


async def _run_sequential(swarm_id, thread_id, prompt, agent_configs, agent_count, agent_type, priority, max_steps, parent_ctx) -> str:
    configs = agent_configs or [
        {"agent_type": agent_type, "name": f"step-{i+1}", "prompt": prompt}
        for i in range(agent_count)
    ]

    previous_result = ""
    all_results = []

    for i, cfg in enumerate(configs):
        enhanced_prompt = cfg.get("prompt", prompt)
        if previous_result:
            enhanced_prompt = f"{enhanced_prompt}\n\n## Previous agent's output (step {i}):\n{previous_result}\n\nContinue from where the previous agent left off."

        agent = await spawn_subagent(
            thread_id=thread_id,
            agent_type=cfg.get("agent_type", agent_type),
            name=cfg.get("name", f"step-{i+1}"),
            prompt=enhanced_prompt,
            priority=cfg.get("priority", priority),
            max_steps=cfg.get("max_steps", max_steps),
            swarm_id=swarm_id,
            parent_ctx=parent_ctx,
        )

        for _ in range(300):
            status = await get_subagent_status(agent.id)
            if status and status["status"] in ("completed", "failed", "killed"):
                previous_result = status.get("result", "")
                all_results.append(status)
                break
            await asyncio.sleep(1)

    return _merge_results(all_results, "sequential")


async def _run_map_reduce(swarm_id, thread_id, prompt, agent_configs, agent_count, agent_type, priority, max_steps, parent_ctx) -> str:
    planner = await spawn_subagent(
        thread_id=thread_id,
        agent_type="planner",
        name="map-planner",
        prompt=f"Break this task into {agent_count} independent subtasks. For each subtask, provide:\n1. A clear description\n2. The expected output format\n\nTask: {prompt}",
        priority="critical",
        max_steps=15,
        swarm_id=swarm_id,
        parent_ctx=parent_ctx,
    )

    planner_result = ""
    for _ in range(300):
        status = await get_subagent_status(planner.id)
        if status and status["status"] in ("completed", "failed", "killed"):
            planner_result = status.get("result", "")
            break
        await asyncio.sleep(1)

    subtasks = _split_subtasks(planner_result, agent_count)
    workers = []
    for i, subtask in enumerate(subtasks):
        worker = await spawn_subagent(
            thread_id=thread_id,
            agent_type=agent_type,
            name=f"map-worker-{i+1}",
            prompt=subtask,
            priority=priority,
            max_steps=max_steps,
            swarm_id=swarm_id,
            parent_ctx=parent_ctx,
        )
        workers.append(worker)

    worker_results = []
    for worker in workers:
        for _ in range(300):
            status = await get_subagent_status(worker.id)
            if status and status["status"] in ("completed", "failed", "killed"):
                worker_results.append(status)
                break
            await asyncio.sleep(1)

    reducer = await spawn_subagent(
        thread_id=thread_id,
        agent_type="coordinator",
        name="reduce-coordinator",
        prompt=(
            f"Merge and synthesize the following {len(worker_results)} results into a "
            f"coherent final report. Remove duplicates, resolve conflicts, and ensure consistency.\n\n"
            f"Original task: {prompt}\n\n"
            + "\n\n---\n\n".join(
                f"Worker {i+1} result:\n{r.get('result', 'No result')}"
                for i, r in enumerate(worker_results)
            )
        ),
        priority="high",
        max_steps=20,
        swarm_id=swarm_id,
        parent_ctx=parent_ctx,
    )

    for _ in range(300):
        status = await get_subagent_status(reducer.id)
        if status and status["status"] in ("completed", "failed", "killed"):
            return status.get("result", "Reduce phase failed")
        await asyncio.sleep(1)

    return "Map-reduce timed out"


async def _run_hierarchical(swarm_id, thread_id, prompt, agent_configs, agent_count, agent_type, priority, max_steps, parent_ctx) -> str:
    coordinator = await spawn_subagent(
        thread_id=thread_id,
        agent_type="coordinator",
        name="hierarchy-coordinator",
        prompt=(
            f"You are coordinating {agent_count} workers for this task:\n{prompt}\n\n"
            f"Break the task into subtasks and assign each to a worker. "
            f"Collect results and produce a final synthesis."
        ),
        priority="critical",
        max_steps=max_steps + 10,
        swarm_id=swarm_id,
        parent_ctx=parent_ctx,
    )

    for _ in range(600):
        status = await get_subagent_status(coordinator.id)
        if status and status["status"] in ("completed", "failed", "killed"):
            return status.get("result", "Coordinator failed")
        await asyncio.sleep(1)

    return "Hierarchical swarm timed out"


def _split_subtasks(planner_output: str, count: int) -> list[str]:
    if not planner_output:
        return ["Complete the assigned portion of the task"] * count

    parts = []
    lines = planner_output.strip().split("\n")
    current_chunk = []

    for line in lines:
        stripped = line.strip()
        if stripped and len(stripped) > 2 and stripped[0].isdigit() and stripped[1] in ".):":
            if current_chunk:
                parts.append("\n".join(current_chunk))
                current_chunk = []
        current_chunk.append(line)

    if current_chunk:
        parts.append("\n".join(current_chunk))

    if len(parts) < count:
        chunk_size = max(1, len(planner_output) // count)
        parts = [planner_output[i:i + chunk_size] for i in range(0, len(planner_output), chunk_size)]

    while len(parts) < count:
        parts.append(f"Complete the assigned portion of the task (part {len(parts)+1})")

    return parts[:count]


def _merge_results(results: list[dict[str, Any]], strategy: str) -> str:
    if not results:
        return "No results collected"

    completed = [r for r in results if r.get("status") == "completed"]
    failed = [r for r in results if r.get("status") == "failed"]
    killed = [r for r in results if r.get("status") == "killed"]

    parts = []

    if completed:
        parts.append(f"## Completed Agents ({len(completed)})")
        for i, r in enumerate(completed):
            name = r.get("name", f"agent-{i+1}")
            agent_type = r.get("agent_type", "unknown")
            result = r.get("result_summary", r.get("result", "No result"))[:1000]
            duration = r.get("duration_ms", 0)
            parts.append(f"### {name} ({agent_type}) — {duration}ms")
            parts.append(result)
            parts.append("")

    if failed:
        parts.append(f"## Failed Agents ({len(failed)})")
        for i, r in enumerate(failed):
            name = r.get("name", f"agent-{i+1}")
            error = r.get("error", "Unknown error")
            parts.append(f"- **{name}**: {error}")

    if killed:
        parts.append(f"## Killed Agents ({len(killed)})")
        for i, r in enumerate(killed):
            name = r.get("name", f"agent-{i+1}")
            parts.append(f"- **{name}**: Killed")

    return "\n\n".join(parts)


async def get_swarm_status(swarm_id: str) -> dict[str, Any] | None:
    async with SessionLocal() as db:
        swarm = await db.get(Swarm, swarm_id)
        if not swarm:
            return None

        query = select(SubAgent).where(SubAgent.swarm_id == swarm_id)
        agents = (await db.execute(query)).scalars().all()

        return {
            "id": swarm.id,
            "thread_id": swarm.thread_id,
            "name": swarm.name,
            "strategy": swarm.strategy,
            "status": swarm.status,
            "prompt": swarm.prompt,
            "agent_count": swarm.agent_count,
            "completed_count": swarm.completed_count,
            "failed_count": swarm.failed_count,
            "result": swarm.result,
            "meta": swarm.meta,
            "agents": [
                {
                    "id": a.id,
                    "name": a.name,
                    "agent_type": a.agent_type,
                    "status": a.status,
                    "priority": a.priority,
                    "result_summary": a.result_summary,
                    "error": a.error,
                    "duration_ms": a.duration_ms,
                    "is_live": runtime.is_running(a.id),
                }
                for a in agents
            ],
        }


async def list_swarms(thread_id: str) -> list[dict[str, Any]]:
    async with SessionLocal() as db:
        query = select(Swarm).where(Swarm.thread_id == thread_id).order_by(Swarm.created_at.desc())
        swarms = (await db.execute(query)).scalars().all()

        return [
            {
                "id": s.id,
                "name": s.name,
                "strategy": s.strategy,
                "status": s.status,
                "agent_count": s.agent_count,
                "completed_count": s.completed_count,
                "failed_count": s.failed_count,
                "result": s.result[:500] if s.result else "",
            }
            for s in swarms
        ]


async def kill_swarm(swarm_id: str) -> int:
    async with SessionLocal() as db:
        query = select(SubAgent).where(
            SubAgent.swarm_id == swarm_id,
            SubAgent.status.in_(["queued", "spawning", "running", "paused"])
        )
        agents = (await db.execute(query)).scalars().all()

        swarm = await db.get(Swarm, swarm_id)
        if swarm:
            swarm.status = "killed"
            await db.commit()

    count = 0
    for agent in agents:
        if await kill_subagent(agent.id):
            count += 1
    return count
