"""Subagents: delegate a self-contained investigation to a nested agent loop.

The child shares the sandbox (so it sees the same files) but gets a fresh context
window, which is the whole point — a long search does not pollute the parent's history.
Only the child's final answer comes back.
"""

from __future__ import annotations

from app.core.utils import truncate
from app.tools.base import ToolContext, ToolResult, integer, obj, string
from app.tools.registry import registry

MAX_DEPTH = 2

AGENT_TYPES = {
    "explorer": (
        "You are a codebase explorer. Search, read and summarise. Never modify files. "
        "Answer with concrete file paths and line numbers."
    ),
    "coder": (
        "You are an implementation subagent. Make the requested change end to end, then "
        "report exactly what you changed."
    ),
    "reviewer": (
        "You are a code reviewer. Inspect the diff and the surrounding code and report only "
        "real defects, each with a file path and a suggested fix."
    ),
    "researcher": (
        "You are a web researcher. Search, fetch and cross-check sources. Report findings "
        "with links and note anything you could not verify."
    ),
}


@registry.tool(
    "task",
    (
        "Launch a subagent for a self-contained job that would otherwise burn a lot of context "
        "(wide code search, multi-file review, deep web research). Give it a complete standalone "
        "prompt — it cannot see this conversation. Only its final report comes back."
    ),
    obj(
        {
            "agent_type": string("Which specialist to run", enum=sorted(AGENT_TYPES)),
            "description": string("Three to six word label shown in the UI"),
            "prompt": string("Full standalone instructions, including paths and expected output format"),
            "max_steps": integer("Tool-step budget for the child", default=25),
        },
        ["agent_type", "description", "prompt"],
    ),
    group="planning",
)
async def task(
    ctx: ToolContext,
    agent_type: str,
    description: str,
    prompt: str,
    max_steps: int = 25,
):
    if ctx.depth >= MAX_DEPTH:
        return ToolResult.error("subagent depth limit reached; do this work directly")
    if agent_type not in AGENT_TYPES:
        return ToolResult.error(f"unknown agent_type: {agent_type}")

    from app.agent.loop import run_subagent  # imported here to avoid a circular import

    await ctx.emit(
        "subagent_start",
        {"tool_call_id": ctx.tool_call_id, "agent_type": agent_type, "description": description},
    )
    try:
        report = await run_subagent(
            parent=ctx,
            system_extra=AGENT_TYPES[agent_type],
            prompt=prompt,
            max_steps=max_steps,
            label=description,
        )
    except Exception as exc:
        await ctx.emit("subagent_end", {"tool_call_id": ctx.tool_call_id, "ok": False})
        return ToolResult.error(f"subagent failed: {exc}")

    await ctx.emit("subagent_end", {"tool_call_id": ctx.tool_call_id, "ok": True})
    return ToolResult(
        content=f"[{agent_type}] {description}\n\n{truncate(report, 40_000)}",
        display={"kind": "subagent", "agent_type": agent_type, "description": description, "report": report},
    )
