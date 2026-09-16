"""Context window accounting and compaction.

When history approaches the model's budget, the oldest turns are replaced by an
LLM-written summary. The most recent turns are always kept verbatim, and a summary
never splits an assistant message from the tool results it produced — that pairing
is what most providers reject.
"""

from __future__ import annotations

import json
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger("app.agent.context")

_KEEP_RECENT = 12


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Cheap character-based estimate; good enough to decide when to compact."""
    total = 0
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str):
            total += len(content)
        elif content:
            total += len(json.dumps(content, default=str))
        for call in msg.get("tool_calls") or []:
            total += len(json.dumps(call, default=str))
    return total // 4 + len(messages) * 4


def _split_point(messages: list[dict[str, Any]], keep_recent: int) -> int:
    """Index of the first kept message, aligned so tool results keep their caller."""
    if len(messages) <= keep_recent:
        return 0
    idx = len(messages) - keep_recent
    while idx < len(messages) and messages[idx].get("role") == "tool":
        idx += 1
    while idx > 0 and messages[idx - 1].get("role") == "assistant" and messages[idx - 1].get("tool_calls"):
        idx -= 1
        while idx > 0 and messages[idx - 1].get("role") == "tool":
            idx -= 1
    return max(0, idx)


def needs_compaction(messages: list[dict[str, Any]], budget: int | None = None) -> bool:
    budget = budget or settings.MAX_CONTEXT_TOKENS
    return estimate_tokens(messages) > budget * settings.COMPACT_AT_RATIO


def transcript(messages: list[dict[str, Any]], limit: int = 60_000) -> str:
    lines: list[str] = []
    for msg in messages:
        role = msg.get("role", "?")
        content = msg.get("content") or ""
        if not isinstance(content, str):
            content = json.dumps(content, default=str)
        if calls := msg.get("tool_calls"):
            names = ", ".join(c.get("function", {}).get("name", "?") for c in calls)
            content = (content + f"\n[called: {names}]").strip()
        lines.append(f"### {role}\n{content[:4000]}")
    text = "\n\n".join(lines)
    return text[-limit:]


async def compact(
    messages: list[dict[str, Any]],
    *,
    client,
    model: str,
    keep_recent: int = _KEEP_RECENT,
) -> tuple[list[dict[str, Any]], str]:
    """Return (new_messages, summary). Falls back to truncation if the LLM call fails."""
    from app.agent.prompts import COMPACT_PROMPT

    split = _split_point(messages, keep_recent)
    if split == 0:
        return messages, ""

    older, recent = messages[:split], messages[split:]
    try:
        completion = await client.complete(
            model=model,
            messages=[
                {"role": "system", "content": COMPACT_PROMPT},
                {"role": "user", "content": transcript(older)},
            ],
            temperature=0.1,
            max_tokens=2000,
        )
        summary = completion.content.strip()
    except Exception as exc:
        log.warning("compaction LLM call failed (%s); truncating instead", exc)
        summary = ""

    if not summary:
        summary = f"[{len(older)} earlier messages were dropped to free context.]"

    carrier = {
        "role": "user",
        "content": f"[Context compacted — summary of earlier turns]\n\n{summary}",
    }
    log.info("compacted %d messages into a summary, kept %d", len(older), len(recent))
    return [carrier, *recent], summary
