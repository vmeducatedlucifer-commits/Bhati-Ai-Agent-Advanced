"""Git Worktree isolation tools matching Claude Code EnterWorktreeTool/ExitWorktreeTool."""

from __future__ import annotations

import os
import shlex

from app.tools.base import ToolContext, ToolResult, boolean, obj, string
from app.tools.registry import registry


@registry.tool(
    "worktree_enter",
    (
        "Create and switch to an isolated Git worktree branch. "
        "Allows working on a new feature or experiment without disturbing the main repository state."
    ),
    obj(
        {
            "branch_name": string("Name of the git branch / worktree to create"),
            "path": string("Relative directory path for the worktree", default=""),
        },
        ["branch_name"],
    ),
    permission="write",
    group="git",
    mutating=True,
)
async def worktree_enter(ctx: ToolContext, branch_name: str, path: str = "") -> ToolResult:
    clean_branch = branch_name.strip().replace(" ", "-")
    target_path = path.strip() or f".worktrees/{clean_branch}"

    cmd = f"git worktree add -B {shlex.quote(clean_branch)} {shlex.quote(target_path)}"
    res = await ctx.sandbox.exec(cmd, timeout=30)
    if res.exit_code != 0:
        return ToolResult.error(f"Failed to create worktree: {res.stderr or res.stdout}")

    return ToolResult(
        content=f"Created and entered isolated worktree at '{target_path}' on branch '{clean_branch}'.",
        display={"kind": "worktree", "branch": clean_branch, "path": target_path},
    )


@registry.tool(
    "worktree_exit",
    "Exit and clean up a Git worktree, optionally deleting the worktree directory.",
    obj(
        {
            "path": string("Path of the worktree directory to remove"),
            "force": boolean("Force removal if there are uncommitted changes", default=False),
        },
        ["path"],
    ),
    permission="dangerous",
    group="git",
    mutating=True,
)
async def worktree_exit(ctx: ToolContext, path: str, force: bool = False) -> ToolResult:
    cmd = f"git worktree remove {'--force' if force else ''} {shlex.quote(path)}"
    res = await ctx.sandbox.exec(cmd, timeout=30)
    if res.exit_code != 0:
        return ToolResult.error(f"Failed to remove worktree '{path}': {res.stderr or res.stdout}")

    return ToolResult(content=f"Successfully removed worktree '{path}'.")
