"""Streaming parsing, context compaction and permission gating."""

from __future__ import annotations

import json

import pytest

from app.agent.context import _split_point, estimate_tokens, needs_compaction
from app.agent.permissions import PermissionBroker
from app.llm.client import _salvage_json, _to_anthropic_messages, _ToolCallAccumulator
from app.tools.base import Tool

# ---------------------------------------------------------------- streaming --


def test_accumulator_stitches_fragmented_tool_calls():
    acc = _ToolCallAccumulator()
    acc.add({"index": 0, "id": "call_a", "function": {"name": "read_file", "arguments": '{"pa'}})
    acc.add({"index": 0, "function": {"arguments": 'th": "a.py"}'}})
    calls = acc.finish()
    assert len(calls) == 1
    assert calls[0].name == "read_file"
    assert calls[0].arguments == {"path": "a.py"}


def test_accumulator_keeps_parallel_calls_separate():
    acc = _ToolCallAccumulator()
    acc.add({"index": 0, "id": "a", "function": {"name": "glob", "arguments": '{"pattern":"*.ts"}'}})
    acc.add({"index": 1, "id": "b", "function": {"name": "grep", "arguments": '{"pattern":"x"}'}})
    calls = acc.finish()
    assert [c.name for c in calls] == ["glob", "grep"]


def test_salvage_recovers_truncated_arguments():
    assert _salvage_json('{"path": "a.py"') == {"path": "a.py"}
    assert _salvage_json("not json at all") == {}


def test_anthropic_conversion_pairs_tool_use_with_results():
    system, messages = _to_anthropic_messages(
        [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"id": "t1", "function": {"name": "bash", "arguments": json.dumps({"command": "ls"})}}
                ],
            },
            {"role": "tool", "tool_call_id": "t1", "content": "a.py"},
        ]
    )
    assert system == "be brief"
    assert messages[1]["content"][0]["type"] == "tool_use"
    assert messages[2]["content"][0]["tool_use_id"] == "t1"


# -------------------------------------------------------------- compaction --


def _history(turns: int) -> list[dict]:
    out: list[dict] = []
    for i in range(turns):
        out.append({"role": "user", "content": f"question {i}"})
        out.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": f"c{i}", "function": {"name": "bash", "arguments": "{}"}}],
            }
        )
        out.append({"role": "tool", "tool_call_id": f"c{i}", "content": "output " * 50})
    return out


def test_estimate_grows_with_content():
    assert estimate_tokens(_history(10)) > estimate_tokens(_history(2))


def test_needs_compaction_respects_the_budget():
    assert not needs_compaction(_history(1), budget=100_000)
    assert needs_compaction(_history(200), budget=1_000)


def test_split_point_never_orphans_a_tool_result():
    history = _history(10)
    index = _split_point(history, keep_recent=5)
    # The first kept message must not be a tool result whose caller was dropped.
    assert history[index]["role"] != "tool"


def test_split_point_keeps_everything_for_short_histories():
    assert _split_point(_history(1), keep_recent=12) == 0


# ------------------------------------------------------------- permissions --


def _tool(name: str, permission: str, mutating: bool) -> Tool:
    async def handler(ctx):
        return "ok"

    return Tool(
        name=name,
        description="test",
        parameters={"type": "object", "properties": {}},
        handler=handler,
        permission=permission,  # type: ignore[arg-type]
        mutating=mutating,
    )


def test_auto_mode_runs_everything_except_the_catastrophic():
    broker = PermissionBroker()
    bash = _tool("bash", "dangerous", True)
    assert broker.needs_approval("t", "auto", bash, {"command": "ls"}) is None
    assert broker.needs_approval("t", "auto", bash, {"command": "rm -rf / --no-preserve-root"})


def test_ask_mode_gates_writes_but_not_reads():
    broker = PermissionBroker()
    assert broker.needs_approval("t", "ask", _tool("read_file", "safe", False), {}) is None
    assert broker.needs_approval("t", "ask", _tool("write_file", "write", True), {})


def test_plan_mode_gates_only_mutations():
    broker = PermissionBroker()
    assert broker.needs_approval("t", "plan", _tool("grep", "safe", False), {}) is None
    assert broker.needs_approval("t", "plan", _tool("bash", "dangerous", True), {})


async def test_allow_always_is_remembered_for_the_thread():
    broker = PermissionBroker()
    tool = _tool("write_file", "write", True)
    assert broker.needs_approval("t", "ask", tool, {})

    import asyncio

    task = asyncio.create_task(broker.ask("t", "req1", "write_file", {}, "because"))
    await asyncio.sleep(0)
    assert broker.resolve("t", "req1", "allow_always")
    assert await task == "allow_always"
    assert broker.needs_approval("t", "ask", tool, {}) is None


def test_resolving_an_unknown_request_is_a_no_op():
    assert PermissionBroker().resolve("t", "missing", "allow") is False


@pytest.mark.parametrize("mode", ["auto", "ask", "plan"])
def test_pending_starts_empty(mode):
    assert PermissionBroker().pending("t") == []
