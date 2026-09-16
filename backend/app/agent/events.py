"""Event names shared by the agent loop, the API and the frontend.

Keep this list in sync with `frontend/src/types/events.ts`.
"""

from __future__ import annotations

from typing import Any, Literal

EventType = Literal[
    "run_start",
    "run_end",
    "message_start",
    "text_delta",
    "reasoning_delta",
    "message_end",
    "tool_call",
    "tool_progress",
    "tool_result",
    "terminal_start",
    "terminal_output",
    "terminal_end",
    "todos",
    "thinking",
    "skill",
    "artifact",
    "memory",
    "preview",
    "preview_stopped",
    "browser_navigate",
    "browser_action",
    "browser_recovery",
    "subagent_start",
    "subagent_end",
    "permission_request",
    "usage",
    "compacted",
    "title",
    "error",
    "interrupted",
]


def event(type_: str, thread_id: str, **payload: Any) -> dict[str, Any]:
    return {"type": type_, "thread_id": thread_id, **payload}
