"""Agent management tools — spawn, kill, list, status, swarm operations."""

from __future__ import annotations

from app.agent.subagent_manager import AGENT_TYPES, PRIORITY_LEVELS
from app.core.utils import truncate
from app.tools.base import ToolContext, ToolResult, integer, obj, string
from app.tools.registry import registry


@registry.tool(
    "agent_spawn",
    (
        "Spawn a new subagent with a specific type and priority. The agent runs independently "
        "in the background. Use this to delegate work to specialized agents. "
        "Available types: " + ", ".join(f"{k}" for k in AGENT_TYPES.keys())
    ),
    obj({
        "agent_type": string("Type of subagent to spawn", enum=sorted(AGENT_TYPES.keys())),
        "name": string("Human-readable name for this agent"),
        "prompt": string("Full standalone instructions for the agent"),
        "priority": string("Priority level: critical, high, normal, low, background", enum=sorted(PRIORITY_LEVELS.keys()), default="normal"),
        "max_steps": integer("Maximum tool steps the agent can take", default=25),
    }, ["agent_type", "name", "prompt"]),
    group="agents",
)
async def agent_spawn(ctx: ToolContext, agent_type: str, name: str, prompt: str, priority: str = "normal", max_steps: int = 25):
    from app.agent.subagent_manager import spawn_subagent
    agent = await spawn_subagent(thread_id=ctx.thread_id, agent_type=agent_type, name=name, prompt=prompt, priority=priority, max_steps=max_steps, parent_ctx=ctx)
    type_config = AGENT_TYPES.get(agent_type, {})
    icon = type_config.get("icon", "🤖")
    return ToolResult(
        content=f"✅ Spawned subagent **{name}** ({icon} {agent_type})\n- **ID**: {agent.id}\n- **Priority**: {priority}\n- **Max Steps**: {max_steps}\n- **Status**: {agent.status}\n\nThe agent is now running in the background. Use `agent_status` to check progress or `agent_kill` to terminate it.",
        display={"kind": "agent_spawn", "agent_id": agent.id, "agent_type": agent_type, "name": name, "priority": priority, "status": agent.status, "icon": icon},
    )


@registry.tool(
    "agent_kill",
    "Kill a running subagent by ID. Use agent_list to find agent IDs.",
    obj({
        "agent_id": string("ID of the subagent to kill"),
        "force": string("Force kill without graceful shutdown", enum=["true", "false"], default="false"),
    }, ["agent_id"]),
    group="agents",
)
async def agent_kill(ctx: ToolContext, agent_id: str, force: str = "false"):
    from app.agent.subagent_manager import kill_subagent
    success = await kill_subagent(agent_id, force=(force == "true"))
    if success:
        return ToolResult(content=f"☠️ Subagent `{agent_id}` has been killed.", display={"kind": "agent_kill", "agent_id": agent_id, "status": "killed"})
    return ToolResult.error(f"Could not kill subagent `{agent_id}`. It may not exist or already be stopped.")


@registry.tool(
    "agent_list",
    "List all subagents for the current thread. Shows status, priority, and result summary.",
    obj({
        "status": string("Filter by status", enum=["queued", "spawning", "running", "paused", "completed", "failed", "killed"], default=""),
    }, []),
    group="agents",
)
async def agent_list(ctx: ToolContext, status: str = ""):
    from app.agent.subagent_manager import list_subagents
    agents = await list_subagents(ctx.thread_id, status=status or None)
    if not agents:
        filter_msg = f" with status '{status}'" if status else ""
        return ToolResult(content=f"No subagents found{filter_msg}.")

    lines = ["## SubAgents\n"]
    for a in agents:
        type_config = AGENT_TYPES.get(a.get("agent_type", ""), {})
        icon = type_config.get("icon", "🤖")
        p_icon = {"critical": "🔴", "high": "🟠", "normal": "🔵", "low": "⚪", "background": "⬛"}.get(a.get("priority", "normal"), "🔵")
        s_icon = {"queued": "⏳", "spawning": "🔄", "running": "▶️", "paused": "⏸️", "completed": "✅", "failed": "❌", "killed": "☠️"}.get(a.get("status", ""), "❓")
        lines.append(f"{s_icon} {icon} **{a.get('name', 'unnamed')}** (`{a.get('id', '')}`)")
        lines.append(f"  - Type: {a.get('agent_type', 'unknown')} | Priority: {p_icon} {a.get('priority', 'normal')} | Status: {a.get('status', 'unknown')}")
        lines.append(f"  - Duration: {a.get('duration_ms', 0)}ms")
        if a.get("result_summary"):
            lines.append(f"  - Result: {truncate(a['result_summary'], 200)}")
        if a.get("error"):
            lines.append(f"  - Error: {a['error']}")
        lines.append("")

    return ToolResult(content="\n".join(lines), display={"kind": "agent_list", "agents": agents})


@registry.tool(
    "agent_status",
    "Get detailed status of a specific subagent. Shows priority, current status, result, error, duration.",
    obj({"agent_id": string("ID of the subagent to inspect")}, ["agent_id"]),
    group="agents",
)
async def agent_status(ctx: ToolContext, agent_id: str):
    from app.agent.subagent_manager import get_subagent_status
    status = await get_subagent_status(agent_id)
    if not status:
        return ToolResult.error(f"Subagent `{agent_id}` not found.")

    type_config = AGENT_TYPES.get(status.get("agent_type", ""), {})
    icon = type_config.get("icon", "🤖")
    lines = [
        f"## {icon} {status.get('name', 'unnamed')} — Detailed Status\n",
        f"- **ID**: {status.get('id', '')}",
        f"- **Type**: {status.get('agent_type', 'unknown')}",
        f"- **Priority**: {status.get('priority', 'normal')}",
        f"- **Status**: {status.get('status', 'unknown')}",
        f"- **Live**: {'Yes' if status.get('is_live') else 'No'}",
        f"- **Max Steps**: {status.get('max_steps', 0)}",
        f"- **Steps Completed**: {status.get('steps_completed', 0)}",
        f"- **Duration**: {status.get('duration_ms', 0)}ms",
        f"- **Started**: {status.get('started_at', 'N/A')}",
        f"- **Finished**: {status.get('finished_at', 'N/A')}",
    ]
    if status.get("swarm_id"):
        lines.append(f"- **Swarm**: {status['swarm_id']}")
    if status.get("result"):
        lines.append(f"\n### Result\n{truncate(status['result'], 3000)}")
    if status.get("error"):
        lines.append(f"\n### Error\n{status['error']}")
    if status.get("tools_blocked"):
        lines.append(f"\n### Blocked Tools\n{', '.join(status['tools_blocked'])}")

    return ToolResult(content="\n".join(lines), display={"kind": "agent_status", "status": status})


@registry.tool(
    "swarm_deploy",
    (
        "Deploy a swarm of coordinated subagents. Strategies:\n"
        "- **parallel**: All agents run simultaneously\n"
        "- **sequential**: Agents run one after another\n"
        "- **map_reduce**: Planner splits → workers parallel → reducer merges\n"
        "- **hierarchical**: Coordinator delegates to workers"
    ),
    obj({
        "name": string("Name for this swarm"),
        "prompt": string("The task/prompt for the swarm to work on"),
        "strategy": string("Deployment strategy", enum=["parallel", "sequential", "map_reduce", "hierarchical"], default="parallel"),
        "agent_count": integer("Number of agents to deploy", default=3),
        "agent_type": string("Type of agents to deploy", enum=sorted(AGENT_TYPES.keys()), default="coder"),
        "priority": string("Priority for all agents", enum=sorted(PRIORITY_LEVELS.keys()), default="normal"),
        "max_steps": integer("Max steps per agent", default=25),
    }, ["name", "prompt", "strategy"]),
    group="agents",
)
async def swarm_deploy(ctx: ToolContext, name: str, prompt: str, strategy: str = "parallel", agent_count: int = 3, agent_type: str = "coder", priority: str = "normal", max_steps: int = 25):
    from app.agent.swarm_manager import deploy_swarm
    swarm = await deploy_swarm(thread_id=ctx.thread_id, name=name, prompt=prompt, strategy=strategy, agent_count=agent_count, agent_type=agent_type, priority=priority, max_steps=max_steps, parent_ctx=ctx)
    strategy_icons = {"parallel": "⚡", "sequential": "🔗", "map_reduce": "🗺️", "hierarchical": "🏗️"}
    icon = strategy_icons.get(strategy, "🐝")
    return ToolResult(
        content=f"{icon} Swarm **{name}** deployed!\n- **ID**: {swarm.id}\n- **Strategy**: {strategy}\n- **Agents**: {agent_count} × {agent_type}\n- **Priority**: {priority}\n- **Status**: {swarm.status}\n\nUse `swarm_status` to monitor progress.",
        display={"kind": "swarm_deploy", "swarm_id": swarm.id, "name": name, "strategy": strategy, "agent_count": agent_count, "status": swarm.status},
    )


@registry.tool(
    "swarm_status",
    "Get detailed status of a swarm including all its agents and their individual progress.",
    obj({"swarm_id": string("ID of the swarm to inspect")}, ["swarm_id"]),
    group="agents",
)
async def swarm_status(ctx: ToolContext, swarm_id: str):
    from app.agent.swarm_manager import get_swarm_status
    status = await get_swarm_status(swarm_id)
    if not status:
        return ToolResult.error(f"Swarm `{swarm_id}` not found.")

    strategy_icons = {"parallel": "⚡", "sequential": "🔗", "map_reduce": "🗺️", "hierarchical": "🏗️"}
    icon = strategy_icons.get(status.get("strategy", ""), "🐝")
    lines = [
        f"## {icon} Swarm: {status.get('name', 'unnamed')}\n",
        f"- **ID**: {status.get('id', '')}",
        f"- **Strategy**: {status.get('strategy', 'unknown')}",
        f"- **Status**: {status.get('status', 'unknown')}",
        f"- **Agents**: {status.get('completed_count', 0)}/{status.get('agent_count', 0)} completed",
    ]
    if status.get("result"):
        lines.append(f"\n### Result\n{truncate(status['result'], 2000)}")

    agents = status.get("agents", [])
    if agents:
        lines.append(f"\n### Agents ({len(agents)})")
        for a in agents:
            a_icon = AGENT_TYPES.get(a.get("agent_type", ""), {}).get("icon", "🤖")
            s_icon = {"queued": "⏳", "spawning": "🔄", "running": "▶️", "paused": "⏸️", "completed": "✅", "failed": "❌", "killed": "☠️"}.get(a.get("status", ""), "❓")
            lines.append(f"  {s_icon} {a_icon} **{a.get('name', 'unnamed')}** — {a.get('status', 'unknown')} | {a.get('priority', 'normal')} | {a.get('duration_ms', 0)}ms")
            if a.get("result_summary"):
                lines.append(f"    Result: {truncate(a['result_summary'], 150)}")
            if a.get("error"):
                lines.append(f"    Error: {a['error']}")

    return ToolResult(content="\n".join(lines), display={"kind": "swarm_status", "status": status})


@registry.tool(
    "swarm_kill",
    "Kill all agents in a swarm and stop the swarm.",
    obj({"swarm_id": string("ID of the swarm to kill")}, ["swarm_id"]),
    group="agents",
)
async def swarm_kill(ctx: ToolContext, swarm_id: str):
    from app.agent.swarm_manager import kill_swarm
    count = await kill_swarm(swarm_id)
    return ToolResult(content=f"☠️ Swarm `{swarm_id}` killed. {count} agent(s) terminated.", display={"kind": "swarm_kill", "swarm_id": swarm_id, "killed_count": count})


@registry.tool(
    "agent_kill_all",
    "Kill all running subagents for the current thread.",
    obj({}, []),
    group="agents",
)
async def agent_kill_all(ctx: ToolContext):
    from app.agent.subagent_manager import kill_all_subagents
    count = await kill_all_subagents(ctx.thread_id)
    return ToolResult(content=f"☠️ Killed {count} running subagent(s).", display={"kind": "agent_kill_all", "killed_count": count})
