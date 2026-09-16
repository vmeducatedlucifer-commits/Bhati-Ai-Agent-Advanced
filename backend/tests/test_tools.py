"""Tool contract: argument binding, edit semantics, plan tracking."""

from __future__ import annotations

import pytest

from app.sandbox.local_sandbox import LocalSandbox
from app.tools import registry
from app.tools.base import ToolContext


@pytest.fixture
async def ctx(tmp_path):
    box = LocalSandbox("test", str(tmp_path))
    await box.start()
    events: list[tuple[str, dict]] = []

    async def emit(type_, payload):
        events.append((type_, payload))

    context = ToolContext(
        thread_id="thr_test",
        project_id="prj_test",
        workspace=str(tmp_path),
        sandbox=box,
        emit=emit,
        tool_call_id="call_1",
    )
    context.state["events"] = events
    return context


async def invoke(ctx, name, **arguments):
    tool = registry.get(name)
    assert tool is not None, f"tool {name} is not registered"
    return await tool.invoke(ctx, arguments)


async def test_write_file_reports_a_diff(ctx):
    result = await invoke(ctx, "write_file", path="a.py", content="x = 1\n")
    assert not result.is_error
    assert result.display["kind"] == "diff"
    assert "+x = 1" in result.display["diff"]


async def test_read_file_is_line_numbered(ctx):
    await invoke(ctx, "write_file", path="a.txt", content="one\ntwo\nthree\n")
    result = await invoke(ctx, "read_file", path="a.txt")
    assert "1\tone" in result.content
    assert "3\tthree" in result.content


async def test_read_file_windows_with_offset_and_limit(ctx):
    await invoke(ctx, "write_file", path="a.txt", content="\n".join(str(i) for i in range(1, 51)))
    result = await invoke(ctx, "read_file", path="a.txt", offset=10, limit=5)
    assert "10\t10" in result.content
    assert "14\t14" in result.content
    assert "15\t15" not in result.content


async def test_edit_file_refuses_ambiguous_matches(ctx):
    await invoke(ctx, "write_file", path="a.py", content="v = 1\nv = 1\n")
    result = await invoke(ctx, "edit_file", path="a.py", old_string="v = 1", new_string="v = 2")
    assert result.is_error
    assert "appears 2 times" in result.content


async def test_edit_file_replace_all(ctx):
    await invoke(ctx, "write_file", path="a.py", content="v = 1\nv = 1\n")
    result = await invoke(ctx, "edit_file", path="a.py", old_string="v = 1", new_string="v = 2", replace_all=True)
    assert not result.is_error
    assert await ctx.sandbox.read_file("a.py") == "v = 2\nv = 2\n"


async def test_edit_file_missing_target_is_an_error(ctx):
    await invoke(ctx, "write_file", path="a.py", content="v = 1\n")
    result = await invoke(ctx, "edit_file", path="a.py", old_string="nope", new_string="x")
    assert result.is_error


async def test_missing_required_argument_is_reported(ctx):
    tool = registry.get("write_file")
    result = await tool.invoke(ctx, {"path": "a.py"})
    assert result.is_error
    assert "content" in result.content


async def test_todo_write_normalises_and_emits(ctx):
    result = await invoke(
        ctx,
        "todo_write",
        todos=[
            {"id": "t1", "title": "First", "status": "in_progress"},
            {"title": "Second", "status": "nonsense"},
            {"title": "", "status": "pending"},
        ],
    )
    todos = ctx.state["todos"]
    assert [t["title"] for t in todos] == ["First", "Second"]
    assert todos[1]["status"] == "pending"
    assert todos[1]["id"] == "t2"
    assert ("todos", {"todos": todos}) in ctx.state["events"]
    assert "1/2" not in result.content  # nothing completed yet


async def test_bash_runs_in_the_sandbox(ctx):
    result = await invoke(ctx, "bash", command="echo sandboxed")
    assert "sandboxed" in result.content
    assert result.display["kind"] == "terminal"


async def test_bash_refuses_catastrophic_commands(ctx):
    result = await invoke(ctx, "bash", command="sudo rm -rf / --no-preserve-root")
    assert result.is_error
    assert "rm -rf /" in result.content


async def test_glob_finds_files(ctx):
    await invoke(ctx, "write_file", path="src/app.ts", content="//")
    await invoke(ctx, "write_file", path="src/util.ts", content="//")
    result = await invoke(ctx, "glob", pattern="*.ts")
    assert "app.ts" in result.content
    assert "util.ts" in result.content


async def test_grep_finds_content(ctx):
    await invoke(ctx, "write_file", path="a.py", content="def target():\n    pass\n")
    result = await invoke(ctx, "grep", pattern="def target")
    assert "a.py" in result.content


async def test_every_tool_exposes_a_valid_schema():
    for tool in registry.all():
        schema = tool.openai_schema()
        assert schema["function"]["name"] == tool.name
        assert schema["function"]["description"]
        params = schema["function"]["parameters"]
        assert params.get("type") == "object"
        for name in params.get("required", []):
            assert name in params.get("properties", {}), f"{tool.name}: required {name} is undeclared"
