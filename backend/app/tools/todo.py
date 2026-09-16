"""Plan / todo tracking — the Manus task list and Claude Code TodoWrite in one tool.

The list lives on the thread row so the UI can render it after a reload, and every
update is broadcast so the plan panel animates while the agent works.
"""

from __future__ import annotations

from typing import Any

from app.tools.base import ToolContext, ToolResult, obj, string
from app.tools.registry import registry

VALID_STATUS = {"pending", "in_progress", "completed", "blocked"}

TODO_SCHEMA = {
    "type": "array",
    "description": "The complete task list. Always send every item, not just changed ones.",
    "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Stable short id, e.g. t1"},
            "title": {"type": "string", "description": "Imperative one-liner, e.g. 'Add auth middleware'"},
            "status": {"type": "string", "enum": sorted(VALID_STATUS)},
            "note": {"type": "string", "description": "Optional detail or blocker reason"},
        },
        "required": ["id", "title", "status"],
        "additionalProperties": False,
    },
}


def normalise(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for index, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", "pending")).lower()
        out.append(
            {
                "id": str(item.get("id") or f"t{index + 1}"),
                "title": str(item.get("title") or "").strip(),
                "status": status if status in VALID_STATUS else "pending",
                "note": str(item.get("note") or ""),
            }
        )
    return [i for i in out if i["title"]]


def render(items: list[dict[str, Any]]) -> str:
    glyphs = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]", "blocked": "[!]"}
    return "\n".join(
        f"{glyphs.get(i['status'], '[ ]')} {i['title']}" + (f" — {i['note']}" if i["note"] else "")
        for i in items
    )


@registry.tool(
    "todo_write",
    (
        "Create or update the task plan for this request. Use it as soon as a request needs "
        "more than two steps, mark exactly one item `in_progress` at a time, and mark items "
        "`completed` the moment they are done. Send the full list on every call."
    ),
    {
        "type": "object",
        "properties": {"todos": TODO_SCHEMA},
        "required": ["todos"],
        "additionalProperties": False,
    },
    group="planning",
)
async def todo_write(ctx: ToolContext, todos: list[dict[str, Any]]):
    items = normalise(todos)
    ctx.state["todos"] = items
    await ctx.emit("todos", {"todos": items})
    done = sum(1 for i in items if i["status"] == "completed")
    return ToolResult(
        content=f"Plan updated ({done}/{len(items)} done)\n{render(items)}",
        display={"kind": "todos", "todos": items},
    )


@registry.tool(
    "think",
    (
        "Write down reasoning before a hard step. Nothing executes; use it to lay out options, "
        "check assumptions, or plan an approach the user can read."
    ),
    obj({"thought": string("Your reasoning")}, ["thought"]),
    group="planning",
)
async def think(ctx: ToolContext, thought: str):
    await ctx.emit("thinking", {"text": thought})
    return ToolResult(content="Noted.", display={"kind": "thinking", "text": thought})
