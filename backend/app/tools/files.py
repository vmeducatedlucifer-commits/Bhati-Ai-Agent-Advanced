"""File tools: read, write, edit, tree, delete — all sandbox-relative."""

from __future__ import annotations

import difflib
import re

from app.core.utils import truncate
from app.tools.base import ToolContext, ToolResult, boolean, integer, obj, string
from app.tools.registry import registry

MAX_READ_CHARS = 120_000
MAX_LINES_DEFAULT = 2000


def _number(text: str, start: int = 1) -> str:
    lines = text.splitlines()
    width = len(str(start + len(lines) - 1))
    return "\n".join(f"{str(i + start).rjust(width)}\t{line}" for i, line in enumerate(lines))


def unified_diff(before: str, after: str, path: str) -> str:
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=3,
        )
    )


@registry.tool(
    "read_file",
    "Read a file from the workspace. Returns line-numbered content. Prefer this over `cat`.",
    obj(
        {
            "path": string("Workspace-relative file path, e.g. src/main.py"),
            "offset": integer("1-based line to start from", default=1),
            "limit": integer("Maximum number of lines to return", default=MAX_LINES_DEFAULT),
        },
        ["path"],
    ),
    group="files",
)
async def read_file(ctx: ToolContext, path: str, offset: int = 1, limit: int = MAX_LINES_DEFAULT):
    try:
        content = await ctx.sandbox.read_file(path)
    except Exception as exc:
        return ToolResult.error(str(exc))
    lines = content.splitlines()
    total = len(lines)
    start = max(1, offset)
    window = lines[start - 1 : start - 1 + max(1, limit)]
    body = truncate("\n".join(window), MAX_READ_CHARS)
    header = f"{path} ({total} lines)"
    if start > 1 or start - 1 + len(window) < total:
        header += f" — showing {start}-{start - 1 + len(window)}"
    return ToolResult(
        content=f"{header}\n{_number(body, start)}",
        display={"kind": "file", "path": path, "content": content, "lines": total},
    )


@registry.tool(
    "write_file",
    "Create or overwrite a file with the given content. Creates parent directories.",
    obj({"path": string("Workspace-relative path"), "content": string("Full file content")}, ["path", "content"]),
    permission="write",
    group="files",
    mutating=True,
)
async def write_file(ctx: ToolContext, path: str, content: str):
    before = ""
    try:
        if await ctx.sandbox.exists(path):
            before = await ctx.sandbox.read_file(path)
    except Exception:
        before = ""
    try:
        size = await ctx.sandbox.write_file(path, content)
    except Exception as exc:
        return ToolResult.error(str(exc))
    diff = unified_diff(before, content, path)
    return ToolResult(
        content=f"Wrote {size} bytes to {path}",
        display={
            "kind": "diff",
            "path": path,
            "diff": diff,
            "created": not before,
            "content": content,
        },
    )


def _strip_line_numbers(text: str) -> str:
    """Strip leading line numbers (e.g., '12\t' or ' 5 | ') if copied from read_file."""
    cleaned = []
    for line in text.splitlines():
        # Match '12\t...' or '12:...' or ' 12 | ...'
        m = re.match(r"^\s*\d+[\t|:]\s?(.*)$", line)
        cleaned.append(m.group(1) if m else line)
    return "\n".join(cleaned)


@registry.tool(
    "edit_file",
    (
        "Replace an exact string in a file. `old_string` must appear exactly once unless "
        "`replace_all` is true. Strip Read line prefixes before matching. "
        "Use this instead of rewriting whole files."
    ),
    obj(
        {
            "path": string("Workspace-relative path"),
            "old_string": string("Exact text to find, including indentation"),
            "new_string": string("Replacement text"),
            "replace_all": boolean("Replace every occurrence", default=False),
        },
        ["path", "old_string", "new_string"],
    ),
    permission="write",
    group="files",
    mutating=True,
)
async def edit_file(
    ctx: ToolContext, path: str, old_string: str, new_string: str, replace_all: bool = False
):
    try:
        before = await ctx.sandbox.read_file(path)
    except Exception as exc:
        return ToolResult.error(f"cannot read {path}: {exc}")

    # Check direct match
    target_old = old_string
    if target_old not in before:
        # Try stripped line numbers
        stripped = _strip_line_numbers(target_old)
        if stripped in before:
            target_old = stripped
            new_string = _strip_line_numbers(new_string)

    occurrences = before.count(target_old)
    if occurrences == 0:
        return ToolResult.error(f"`old_string` not found in {path}. Make sure the snippet matches the file exactly.")
    if occurrences > 1 and not replace_all:
        return ToolResult.error(
            f"`old_string` appears {occurrences} times in {path}. "
            "Add surrounding context to make it unique, or set replace_all=true."
        )

    after = before.replace(target_old, new_string) if replace_all else before.replace(target_old, new_string, 1)
    await ctx.sandbox.write_file(path, after)
    diff = unified_diff(before, after, path)
    return ToolResult(
        content=f"Applied {occurrences if replace_all else 1} replacement(s) in {path}\n{truncate(diff, 6000)}",
        display={"kind": "diff", "path": path, "diff": diff, "content": after},
    )


@registry.tool(
    "list_files",
    "List a directory in the workspace. Use `recursive` for a tree view.",
    obj(
        {
            "path": string("Directory, empty for workspace root", default=""),
            "recursive": boolean("Walk subdirectories", default=False),
            "max_entries": integer("Cap on returned entries", default=400),
        }
    ),
    group="files",
)
async def list_files(ctx: ToolContext, path: str = "", recursive: bool = False, max_entries: int = 400):
    if recursive:
        entries = await ctx.sandbox.list_dir(path)
        all_paths: list[str] = [e.path for e in entries]
        visited: set[str] = set()
        queue = list(entries)
        while queue and len(all_paths) < max_entries:
            entry = queue.pop(0)
            if entry.is_dir and entry.path not in visited:
                visited.add(entry.path)
                try:
                    sub = await ctx.sandbox.list_dir(entry.path)
                    for s in sub:
                        full = f"{entry.path}/{s.name}" if entry.path else s.name
                        all_paths.append(full)
                        if s.is_dir:
                            queue.append(s)
                except Exception:
                    pass
        listing = "\n".join(all_paths[:max_entries]) or "(empty)"
        return ToolResult(
            content=f"{path or '.'}:\n{listing}",
            display={"kind": "tree", "path": path, "entries": all_paths[:max_entries]},
        )

    entries = await ctx.sandbox.list_dir(path)
    if not entries:
        return ToolResult(content=f"{path or '.'} is empty", display={"kind": "tree", "path": path, "entries": []})
    lines = [f"{'📁' if e.is_dir else '📄'} {e.name}{'/' if e.is_dir else f'  ({e.size}b)'}" for e in entries[:max_entries]]
    return ToolResult(
        content=f"{path or '.'}:\n" + "\n".join(lines),
        display={
            "kind": "tree",
            "path": path,
            "entries": [{"name": e.name, "path": e.path, "is_dir": e.is_dir, "size": e.size} for e in entries],
        },
    )


@registry.tool(
    "delete_file",
    "Delete a file or directory from the workspace.",
    obj({"path": string("Workspace-relative path")}, ["path"]),
    permission="dangerous",
    group="files",
    mutating=True,
)
async def delete_file(ctx: ToolContext, path: str):
    try:
        await ctx.sandbox.delete(path)
    except Exception as exc:
        return ToolResult.error(str(exc))
    return ToolResult(content=f"Deleted {path}", display={"kind": "text", "text": f"Deleted {path}"})
