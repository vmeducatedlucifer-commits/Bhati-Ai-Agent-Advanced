"""Permission gating — uncensored hard default.

Default path: allow everything. bypass/auto/uncensored skip prompts.
ALWAYS_ASK emptied. ask mode still exists but is not the default.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from typing import Literal

from app.tools.base import Tool

Decision = Literal["allow", "deny", "allow_always"]

# Critical command substrings that require explicit confirmation even in standard runs
ALWAYS_ASK_SUBSTRINGS: tuple[str, ...] = (
    "rm -rf",
    "git reset --hard",
    "git clean -fdx",
    "drop table",
    "drop database",
    "truncate table",
    "killall",
    "shutdown",
    "reboot",
)


def args_fingerprint(arguments: dict) -> str:
    """Stable hash of tool arguments — allow_always is scoped to these."""
    try:
        canonical = json.dumps(arguments, sort_keys=True, default=str)
    except (TypeError, ValueError):
        canonical = str(arguments)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


@dataclass
class PendingPermission:
    id: str
    tool: str
    arguments: dict
    reason: str
    future: asyncio.Future = field(repr=False)


class PermissionBroker:
    """Holds questions the agent is waiting on, keyed by thread."""

    def __init__(self) -> None:
        self._pending: dict[str, dict[str, PendingPermission]] = {}
        self._always: dict[str, set[tuple[str, str]]] = {}

    def needs_approval(self, thread_id: str, mode: str, tool: Tool, arguments: dict) -> str | None:
        """Returns a reason string when approval is required, else None."""
        if (tool.name, args_fingerprint(arguments)) in self._always.get(thread_id, set()):
            return None

        command = str(arguments.get("command", "")).lower()
        for pattern in ALWAYS_ASK_SUBSTRINGS:
            if pattern in command:
                return f"`{pattern}` is destructive"

        normalized = (mode or "auto").lower().strip()
        if normalized in ("bypass", "auto", "uncensored", "", "open"):
            return None

        if normalized == "plan":
            return "plan mode: nothing runs without approval" if tool.mutating else None
        # mode == "ask"
        if tool.permission == "dangerous":
            return "runs a command in the sandbox"
        if tool.permission == "write":
            return "modifies files or remote state"
        return None

    async def ask(
        self, thread_id: str, request_id: str, tool: str, arguments: dict, reason: str, timeout: float = 900.0
    ) -> Decision:
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending.setdefault(thread_id, {})[request_id] = PendingPermission(
            id=request_id, tool=tool, arguments=arguments, reason=reason, future=future
        )
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError:
            # Safe default: on timeout, deny execution.
            return "deny"
        finally:
            self._pending.get(thread_id, {}).pop(request_id, None)

    def resolve(self, thread_id: str, request_id: str, decision: Decision) -> bool:
        pending = self._pending.get(thread_id, {}).get(request_id)
        if not pending or pending.future.done():
            return False
        if decision == "allow_always":
            self._always.setdefault(thread_id, set()).add(
                (pending.tool, args_fingerprint(pending.arguments))
            )
        pending.future.set_result(decision)
        return True

    def pending(self, thread_id: str) -> list[dict]:
        return [
            {"id": p.id, "tool": p.tool, "arguments": p.arguments, "reason": p.reason}
            for p in self._pending.get(thread_id, {}).values()
        ]

    def clear(self, thread_id: str) -> None:
        for pending in self._pending.pop(thread_id, {}).values():
            if not pending.future.done():
                pending.future.cancel()
        self._always.pop(thread_id, None)


permissions = PermissionBroker()
