"""Interactive user questioning tool matching Claude Code AskUserQuestionTool."""

from __future__ import annotations

from typing import Any

from app.tools.base import ToolContext, ToolResult, boolean, obj, string
from app.tools.registry import registry


@registry.tool(
    "question",
    (
        "Ask the user one or more clarifying questions or present implementation choices. "
        "Allows gathering user preferences, clarifying ambiguous instructions, or getting decisions."
    ),
    obj(
        {
            "questions": {
                "type": "array",
                "description": "List of questions to present to the user",
                "items": {
                    "type": "object",
                    "properties": {
                        "header": string("Very short label (max 30 chars)"),
                        "question": string("Complete question to ask"),
                        "options": {
                            "type": "array",
                            "description": "Available choices",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "label": string("Display text (1-5 words)"),
                                    "description": string("Explanation of choice"),
                                },
                                "required": ["label", "description"],
                            },
                        },
                        "multiple": boolean("Allow selecting multiple choices", default=False),
                    },
                    "required": ["header", "question", "options"],
                },
            }
        },
        ["questions"],
    ),
    permission="safe",
    group="general",
    mutating=False,
)
async def question(ctx: ToolContext, questions: list[dict[str, Any]]) -> ToolResult:
    # Emit event so the UI displays interactive question cards
    await ctx.emit(
        "question_request",
        {"tool_call_id": ctx.tool_call_id, "questions": questions},
    )

    formatted = []
    for idx, q in enumerate(questions, 1):
        opts = "\n".join(f"  - {opt.get('label')}: {opt.get('description')}" for opt in q.get("options", []))
        formatted.append(f"Q{idx}: {q.get('question')}\nOptions:\n{opts}")

    return ToolResult(
        content="Presented questions to user:\n\n" + "\n\n".join(formatted),
        display={"kind": "question", "questions": questions},
    )
