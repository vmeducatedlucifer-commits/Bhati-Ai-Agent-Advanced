"""Git tools driven through the sandbox shell so they see the real working tree."""

from __future__ import annotations

import shlex

from app.core.utils import truncate
from app.tools.base import ToolContext, ToolResult, boolean, integer, obj, string
from app.tools.registry import registry


async def _git(ctx: ToolContext, args: str, timeout: int = 120):
    return await ctx.sandbox.exec(f"git {args}", timeout=timeout)


@registry.tool(
    "git_status",
    "Show the working tree status and current branch.",
    obj({}),
    group="git",
)
async def git_status(ctx: ToolContext):
    res = await _git(ctx, "status --short --branch")
    if res.exit_code != 0:
        return ToolResult.error(res.combined() or "not a git repository")
    return ToolResult(
        content=res.stdout.strip() or "clean working tree",
        display={"kind": "git_status", "output": res.stdout},
    )


@registry.tool(
    "git_diff",
    "Show unstaged (or staged) changes as a unified diff.",
    obj(
        {
            "staged": boolean("Show staged changes instead", default=False),
            "path": string("Limit the diff to a path", default=""),
        }
    ),
    group="git",
)
async def git_diff(ctx: ToolContext, staged: bool = False, path: str = ""):
    args = "diff --no-color" + (" --cached" if staged else "")
    if path:
        args += f" -- {shlex.quote(path)}"
    res = await _git(ctx, args)
    diff = res.stdout
    return ToolResult(
        content=truncate(diff, 25_000) or "no changes",
        display={"kind": "diff", "path": path or "working tree", "diff": diff},
    )


@registry.tool(
    "git_log",
    "Show recent commits.",
    obj({"limit": integer("How many commits", default=15)}),
    group="git",
)
async def git_log(ctx: ToolContext, limit: int = 15):
    res = await _git(ctx, f"log --oneline --decorate -n {int(limit)}")
    return ToolResult(
        content=res.stdout.strip() or "no commits",
        display={"kind": "list", "title": "git log", "items": res.stdout.splitlines()},
    )


@registry.tool(
    "git_commit",
    "Stage files and create a commit. Pass `paths` to stage specific files, otherwise everything.",
    obj(
        {
            "message": string("Commit message"),
            "paths": string("Space-separated paths to stage", default=""),
        },
        ["message"],
    ),
    permission="write",
    group="git",
    mutating=True,
)
async def git_commit(ctx: ToolContext, message: str, paths: str = ""):
    await _git(ctx, "config user.email >/dev/null 2>&1 || git config user.email agent@rawal.local")
    await _git(ctx, "config user.name >/dev/null 2>&1 || git config user.name 'Rawal AI'")
    stage = await _git(ctx, f"add {paths if paths else '-A'}")
    if stage.exit_code != 0:
        return ToolResult.error(stage.combined())
    res = await _git(ctx, f"commit -m {shlex.quote(message)}")
    if res.exit_code != 0 and "nothing to commit" in res.combined().lower():
        return ToolResult(content="nothing to commit")
    if res.exit_code != 0:
        return ToolResult.error(res.combined())
    return ToolResult(content=res.stdout.strip(), display={"kind": "text", "text": res.stdout})


@registry.tool(
    "git_clone",
    "Clone a repository into the workspace.",
    obj(
        {
            "url": string("Repository URL"),
            "directory": string("Target directory name", default=""),
            "depth": integer("Shallow clone depth, 0 for full", default=1),
        },
        ["url"],
    ),
    permission="write",
    group="git",
    mutating=True,
)
async def git_clone(ctx: ToolContext, url: str, directory: str = "", depth: int = 1):
    args = "clone"
    if depth:
        args += f" --depth {int(depth)}"
    args += f" {shlex.quote(url)}"
    if directory:
        args += f" {shlex.quote(directory)}"
    res = await _git(ctx, args, timeout=600)
    if res.exit_code != 0:
        return ToolResult.error(res.combined())
    return ToolResult(content=res.combined() or f"cloned {url}")


@registry.tool(
    "git_branch",
    "Create, switch, or list branches.",
    obj(
        {
            "action": string("What to do", enum=["list", "create", "switch"]),
            "name": string("Branch name for create/switch", default=""),
        },
        ["action"],
    ),
    permission="write",
    group="git",
    mutating=True,
)
async def git_branch(ctx: ToolContext, action: str, name: str = ""):
    if action == "list":
        res = await _git(ctx, "branch -a --no-color")
    elif action == "create":
        res = await _git(ctx, f"checkout -b {shlex.quote(name)}")
    elif action == "switch":
        res = await _git(ctx, f"checkout {shlex.quote(name)}")
    else:
        return ToolResult.error(f"unknown action: {action}")
    if res.exit_code != 0:
        return ToolResult.error(res.combined())
    return ToolResult(content=res.combined().strip() or "ok")
