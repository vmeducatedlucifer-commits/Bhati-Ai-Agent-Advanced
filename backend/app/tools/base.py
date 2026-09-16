"""Tool contract: schema, permission tier, and the context handed to every call."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from app.sandbox.base import Sandbox

Permission = Literal["safe", "write", "dangerous"]

EmitFn = Callable[[str, dict[str, Any]], Awaitable[None]]


@dataclass
class ToolContext:
    """Everything a tool may touch, injected by the agent loop."""

    thread_id: str
    project_id: str
    workspace: str
    sandbox: Sandbox
    emit: EmitFn
    tool_call_id: str = ""
    depth: int = 0
    state: dict[str, Any] = field(default_factory=dict)

    async def progress(self, text: str) -> None:
        await self.emit("tool_progress", {"tool_call_id": self.tool_call_id, "text": text})


@dataclass(slots=True)
class ToolResult:
    """What a tool hands back.

    `content` goes to the model. `display` is a structured payload for the UI so the
    "agent computer" panel can render a diff, a file tree, or a terminal instead of
    another wall of text.
    """

    content: str
    display: dict[str, Any] | None = None
    is_error: bool = False

    @classmethod
    def error(cls, message: str) -> ToolResult:
        return cls(content=f"ERROR: {message}", is_error=True)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Awaitable[Any]]
    permission: Permission = "safe"
    group: str = "general"
    # Tools the model should not see in plan-only mode.
    mutating: bool = False

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    async def invoke(self, ctx: ToolContext, arguments: dict[str, Any]) -> ToolResult:
        if not isinstance(arguments, dict):
            return ToolResult.error("arguments must be an object")
        problem = self._validate_arguments(arguments)
        if problem:
            return ToolResult.error(problem)
        sig = inspect.signature(self.handler)
        kwargs: dict[str, Any] = {}
        for param in sig.parameters.values():
            if param.name == "ctx":
                kwargs["ctx"] = ctx
            elif param.name in arguments:
                kwargs[param.name] = arguments[param.name]
        missing = [
            p.name
            for p in sig.parameters.values()
            if p.name not in kwargs and p.default is inspect.Parameter.empty and p.name != "ctx"
        ]
        if missing:
            return ToolResult.error(f"missing required argument(s): {', '.join(missing)}")
        out = await self.handler(**kwargs)
        if isinstance(out, ToolResult):
            return out
        return ToolResult(content=str(out))

    def _validate_arguments(self, arguments: dict[str, Any]) -> str | None:
        """Light schema check: required present + no confused container types.

        Deliberately lenient (models fumble scalar types) — it only rejects
        what is certainly wrong: missing required keys and dict/list values
        where the schema declares a scalar.
        """
        schema = self.parameters or {}
        if not isinstance(schema, dict) or schema.get("type") != "object":
            return None
        properties = schema.get("properties") or {}
        for required in schema.get("required") or []:
            if required not in arguments:
                return f"missing required argument: {required}"
        for key, value in arguments.items():
            declared = (properties.get(key) or {}).get("type") if isinstance(properties.get(key), dict) else None
            if declared in ("string", "integer", "number", "boolean") and isinstance(value, (dict, list)):
                return f"argument `{key}` must be {declared}, not {type(value).__name__}"
        return None


def string(desc: str, **extra: Any) -> dict[str, Any]:
    return {"type": "string", "description": desc, **extra}


def integer(desc: str, **extra: Any) -> dict[str, Any]:
    return {"type": "integer", "description": desc, **extra}


def boolean(desc: str, **extra: Any) -> dict[str, Any]:
    return {"type": "boolean", "description": desc, **extra}


def obj(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }
