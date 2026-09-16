"""API endpoints for subagent and swarm management."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/agents", tags=["agents"])


class SpawnRequest(BaseModel):
    thread_id: str
    agent_type: str
    name: str = ""
    prompt: str
    priority: str = "normal"
    max_steps: int = 25


class KillRequest(BaseModel):
    force: bool = False


class SwarmDeployRequest(BaseModel):
    thread_id: str
    name: str
    prompt: str
    strategy: str = "parallel"
    agent_count: int = 3
    agent_type: str = "coder"
    priority: str = "normal"
    max_steps: int = 25


# ── Agent types info (MUST be before /{thread_id} to avoid route conflict) ──────

@router.get("/types/info", summary="List available agent types")
async def list_agent_types():
    from app.agent.subagent_manager import AGENT_TYPES, PRIORITY_LEVELS
    return {
        "agent_types": {
            k: {
                "system_prompt": v["system_prompt"][:200],
                "priority_default": v["priority_default"],
                "max_steps_default": v["max_steps_default"],
                "icon": v["icon"],
                "color": v["color"],
            }
            for k, v in AGENT_TYPES.items()
        },
        "priority_levels": PRIORITY_LEVELS,
        "strategies": ["parallel", "sequential", "map_reduce", "hierarchical"],
    }


# ── SubAgent endpoints ──────────────────────────────────────────────────────

@router.get("/{thread_id}", summary="List subagents for a thread")
async def list_agents(thread_id: str, status: str | None = None):
    from app.agent.subagent_manager import list_subagents
    agents = await list_subagents(thread_id, status=status)
    return {"agents": agents}


@router.get("/{thread_id}/{agent_id}", summary="Get subagent status")
async def get_agent_status(thread_id: str, agent_id: str):
    from app.agent.subagent_manager import get_subagent_status
    status = await get_subagent_status(agent_id)
    if not status:
        raise HTTPException(404, f"SubAgent {agent_id} not found")
    return status


@router.post("/{thread_id}/spawn", summary="Spawn a new subagent")
async def spawn_agent(thread_id: str, req: SpawnRequest):
    from app.agent.subagent_manager import spawn_subagent, AGENT_TYPES
    if req.agent_type not in AGENT_TYPES:
        raise HTTPException(400, f"Unknown agent_type: {req.agent_type}")
    agent = await spawn_subagent(thread_id=thread_id, agent_type=req.agent_type, name=req.name, prompt=req.prompt, priority=req.priority, max_steps=req.max_steps)
    return {"id": agent.id, "status": agent.status, "name": agent.name}


@router.post("/{thread_id}/{agent_id}/kill", summary="Kill a subagent")
async def kill_agent(thread_id: str, agent_id: str, req: KillRequest | None = None):
    from app.agent.subagent_manager import kill_subagent
    force = req.force if req else False
    success = await kill_subagent(agent_id, force=force)
    if not success:
        raise HTTPException(404, f"SubAgent {agent_id} not found or already stopped")
    return {"status": "killed", "agent_id": agent_id}


@router.post("/{thread_id}/{agent_id}/pause", summary="Pause a subagent")
async def pause_agent(thread_id: str, agent_id: str):
    from app.agent.subagent_manager import pause_subagent
    success = await pause_subagent(agent_id)
    if not success:
        raise HTTPException(400, f"Cannot pause subagent {agent_id}")
    return {"status": "paused", "agent_id": agent_id}


@router.post("/{thread_id}/{agent_id}/resume", summary="Resume a paused subagent")
async def resume_agent(thread_id: str, agent_id: str):
    from app.agent.subagent_manager import resume_subagent
    success = await resume_subagent(agent_id)
    if not success:
        raise HTTPException(400, f"Cannot resume subagent {agent_id}")
    return {"status": "running", "agent_id": agent_id}


@router.post("/{thread_id}/kill-all", summary="Kill all running subagents")
async def kill_all_agents(thread_id: str):
    from app.agent.subagent_manager import kill_all_subagents
    count = await kill_all_subagents(thread_id)
    return {"killed_count": count}


# ── Swarm endpoints ──────────────────────────────────────────────────────────

@router.get("/{thread_id}/swarms", summary="List swarms for a thread")
async def list_swarms(thread_id: str):
    from app.agent.swarm_manager import list_swarms as _list
    swarms = await _list(thread_id)
    return {"swarms": swarms}


@router.get("/{thread_id}/swarms/{swarm_id}", summary="Get swarm status")
async def get_swarm_status(thread_id: str, swarm_id: str):
    from app.agent.swarm_manager import get_swarm_status as _get
    status = await _get(swarm_id)
    if not status:
        raise HTTPException(404, f"Swarm {swarm_id} not found")
    return status


@router.post("/{thread_id}/swarms/deploy", summary="Deploy a swarm")
async def deploy_swarm(thread_id: str, req: SwarmDeployRequest):
    from app.agent.swarm_manager import deploy_swarm as _deploy
    swarm = await _deploy(thread_id=thread_id, name=req.name, prompt=req.prompt, strategy=req.strategy, agent_count=req.agent_count, agent_type=req.agent_type, priority=req.priority, max_steps=req.max_steps)
    return {"id": swarm.id, "status": swarm.status, "name": swarm.name}


@router.post("/{thread_id}/swarms/{swarm_id}/kill", summary="Kill a swarm")
async def kill_swarm(thread_id: str, swarm_id: str):
    from app.agent.swarm_manager import kill_swarm as _kill
    count = await _kill(swarm_id)
    return {"status": "killed", "swarm_id": swarm_id, "killed_count": count}


# ── Agent types info ─────────────────────────────────────────────────────────

@router.get("/types/info", summary="List available agent types")
async def list_agent_types():
    from app.agent.subagent_manager import AGENT_TYPES, PRIORITY_LEVELS
    return {
        "agent_types": {
            k: {
                "system_prompt": v["system_prompt"][:200],
                "priority_default": v["priority_default"],
                "max_steps_default": v["max_steps_default"],
                "icon": v["icon"],
                "color": v["color"],
            }
            for k, v in AGENT_TYPES.items()
        },
        "priority_levels": PRIORITY_LEVELS,
        "strategies": ["parallel", "sequential", "map_reduce", "hierarchical"],
    }
