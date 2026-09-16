"""Import every tool module so the registry is populated, then expose helpers."""

from __future__ import annotations

from app.agent import memory  # noqa: F401
from app.tools import (  # noqa: F401  (imported for their registration side effects)
    agents,
    artifacts,
    browser,
    commit_pr,
    files,
    git,
    integrations,
    notebook,
    plan,
    preview,
    question,
    review,
    search,
    shell,
    synthetic,
    task,
    todo,
    web,
    worktree,
)
from app.tools.base import Tool, ToolContext, ToolResult
from app.tools.registry import registry

__all__ = ["Tool", "ToolContext", "ToolResult", "registry", "builtin_tool_names"]


def builtin_tool_names() -> list[str]:
    return registry.names()
