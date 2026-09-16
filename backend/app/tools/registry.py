"""The tool registry the agent loop reads from."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.core.logging import get_logger
from app.tools.base import Permission, Tool

log = get_logger("app.tools.registry")


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> Tool:
        if tool.name in self._tools:
            log.debug("replacing tool %s", tool.name)
        self._tools[tool.name] = tool
        return tool

    def tool(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        *,
        permission: Permission = "safe",
        group: str = "general",
        mutating: bool = False,
    ) -> Callable:
        def decorator(fn):
            self.register(
                Tool(
                    name=name,
                    description=description,
                    parameters=parameters,
                    handler=fn,
                    permission=permission,
                    group=group,
                    mutating=mutating,
                )
            )
            return fn

        return decorator

    def unregister_prefix(self, prefix: str) -> int:
        removed = [k for k in self._tools if k.startswith(prefix)]
        for key in removed:
            del self._tools[key]
        return len(removed)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def names(self) -> list[str]:
        return sorted(self._tools)

    def schemas(self, *, exclude: set[str] | None = None, read_only: bool = False) -> list[dict[str, Any]]:
        exclude = exclude or set()
        return [
            t.openai_schema()
            for t in self._tools.values()
            if t.name not in exclude and not (read_only and t.mutating)
        ]

    def describe(self) -> list[dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "group": t.group,
                "permission": t.permission,
                "mutating": t.mutating,
                "parameters": t.parameters,
            }
            for t in sorted(self._tools.values(), key=lambda x: (x.group, x.name))
        ]


registry = ToolRegistry()
