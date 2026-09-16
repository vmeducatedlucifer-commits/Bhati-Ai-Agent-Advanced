"""Local sandbox behaviour: confinement, exec, streaming, file round-trips."""

from __future__ import annotations

import sys

import pytest

from app.core.errors import AppError
from app.sandbox.local_sandbox import LocalSandbox


@pytest.fixture
async def sandbox(tmp_path):
    box = LocalSandbox("test", str(tmp_path))
    await box.start()
    return box


async def test_write_then_read_round_trips(sandbox):
    size = await sandbox.write_file("nested/dir/note.txt", "hello\n")
    assert size == 6
    assert await sandbox.read_file("nested/dir/note.txt") == "hello\n"


async def test_paths_cannot_escape_the_workspace(sandbox):
    with pytest.raises(AppError):
        await sandbox.write_file("../escaped.txt", "nope")


async def test_exec_returns_exit_code_and_output(sandbox):
    if sys.platform == "win32":
        result = await sandbox.exec("echo hi & exit 3")
    else:
        result = await sandbox.exec("echo hi && exit 3")
    assert result.exit_code == 3
    assert "hi" in result.stdout
    assert not result.ok


async def test_exec_times_out_without_hanging(sandbox):
    if sys.platform == "win32":
        # ping -n 6 127.0.0.1 waits ~5 seconds on Windows
        result = await sandbox.exec("ping -n 6 127.0.0.1 >nul 2>nul", timeout=1)
    else:
        result = await sandbox.exec("sleep 5", timeout=1)
    assert result.timed_out
    assert result.exit_code == 124


async def test_exec_stream_yields_incrementally(sandbox):
    if sys.platform == "win32":
        chunks = [chunk async for chunk in sandbox.exec_stream("echo a& echo b& echo c")]
    else:
        chunks = [chunk async for chunk in sandbox.exec_stream("printf 'a\\nb\\nc\\n'")]
    combined = "".join(chunks).replace("\r\n", "\n").replace("\r", "\n")
    lines = [line for line in combined.splitlines() if line.strip()]
    assert "a" in lines
    assert "b" in lines
    assert "c" in lines


async def test_list_dir_sorts_directories_first(sandbox):
    await sandbox.write_file("b.txt", "x")
    await sandbox.write_file("adir/inner.txt", "x")
    entries = await sandbox.list_dir("")
    assert [e.name for e in entries] == ["adir", "b.txt"]
    assert entries[0].is_dir


async def test_delete_refuses_the_root(sandbox):
    with pytest.raises(AppError):
        await sandbox.delete("")
