"""Plan Mode Toolset: Plan Design, Review, and Execution Transitions."""

from __future__ import annotations

from pathlib import Path

from app.tools.base import ToolContext, ToolResult, obj, string
from app.tools.registry import registry

PLAN_FILE_NAME = ".agent/plan.md"


@registry.tool(
    "enter_plan_mode",
    (
        "Transition into Plan Mode. Use proactively when starting a non-trivial or multi-file task. "
        "Allows exploring the codebase and designing an implementation approach for user sign-off before writing code."
    ),
    obj({"reason": string("Brief explanation of why you are entering plan mode")}, ["reason"]),
    group="planning",
)
async def enter_plan_mode(ctx: ToolContext, reason: str):
    plan_file = Path(ctx.workspace) / PLAN_FILE_NAME
    plan_file.parent.mkdir(parents=True, exist_ok=True)
    if not plan_file.exists():
        plan_file.write_text("# Implementation Plan\n\n- [ ] Initial exploration\n", encoding="utf-8")

    await ctx.emit("plan_mode_entered", {"reason": reason})
    return ToolResult(
        content=(
            f"Entered Plan Mode: {reason}.\n"
            "You can now explore the codebase, research files, and draft your plan in `.agent/plan.md`. "
            "When finished, call `exit_plan_mode` for user approval."
        ),
        display={"kind": "plan_mode", "status": "active", "reason": reason},
    )


@registry.tool(
    "exit_plan_mode",
    (
        "Exit Plan Mode when you have finished writing your plan to `.agent/plan.md` and are ready for user review/approval. "
        "Signals that planning is complete."
    ),
    obj({}, []),
    group="planning",
)
async def exit_plan_mode(ctx: ToolContext):
    plan_file = Path(ctx.workspace) / PLAN_FILE_NAME
    plan_content = ""
    if plan_file.exists():
        plan_content = plan_file.read_text(encoding="utf-8", errors="ignore")

    await ctx.emit("plan_mode_exited", {"plan": plan_content})
    return ToolResult(
        content=(
            "Exited Plan Mode. The plan has been presented for user approval.\n\n"
            f"{plan_content}"
        ),
        display={"kind": "plan", "status": "submitted", "content": plan_content},
    )
