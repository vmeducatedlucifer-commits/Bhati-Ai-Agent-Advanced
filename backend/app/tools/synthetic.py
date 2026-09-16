"""Structured schema output generator matching Anthropic SyntheticOutputTool."""

from __future__ import annotations

import json
from typing import Any

from app.tools.base import ToolContext, ToolResult, obj, string
from app.tools.registry import registry


@registry.tool(
    "synthetic_output",
    "Generate a structured JSON output conforming to a specific schema.",
    obj(
        {
            "output": {
                "type": "object",
                "description": "Structured JSON payload to return",
            },
        },
        ["output"],
    ),
    permission="safe",
    group="general",
    mutating=False,
)
async def synthetic_output(ctx: ToolContext, output: dict[str, Any]) -> ToolResult:
    formatted = json.dumps(output, indent=2)
    return ToolResult(
        content=formatted,
        display={"kind": "synthetic_output", "data": output},
    )
