"""Git Commit, Push, and PR automation matching Anthropic commit-commands plugin."""

from __future__ import annotations

import shlex

from app.tools.base import ToolContext, ToolResult, boolean, obj, string
from app.tools.registry import registry


@registry.tool(
    "commit_push_pr",
    (
        "Automates the full Git release pipeline: creates a feature branch, stages files, "
        "creates a conventional commit, pushes to remote, and opens a GitHub Pull Request using `gh pr create`."
    ),
    obj(
        {
            "branch_name": string("Name of the feature branch (e.g. `feat/add-auth`)"),
            "commit_message": string("Conventional commit message (e.g. `feat(auth): implement jwt token auth`)"),
            "pr_title": string("Pull Request title", default=""),
            "pr_body": string("Pull Request description and summary of changes", default=""),
            "draft": boolean("Create as Draft PR", default=False),
        },
        ["branch_name", "commit_message"],
    ),
    permission="dangerous",
    group="git",
    mutating=True,
)
async def commit_push_pr(
    ctx: ToolContext,
    branch_name: str,
    commit_message: str,
    pr_title: str = "",
    pr_body: str = "",
    draft: bool = False,
) -> ToolResult:
    clean_branch = branch_name.strip().replace(" ", "-")
    title = pr_title.strip() or commit_message.strip()
    body = pr_body.strip() or f"Automated pull request created by Rawal AI.\n\n### Changes:\n- {commit_message}"

    pipeline_cmds = [
        f"git checkout -B {shlex.quote(clean_branch)}",
        "git add -A",
        f"git commit -m {shlex.quote(commit_message)}",
        f"git push -u origin {shlex.quote(clean_branch)}",
        f"gh pr create --title {shlex.quote(title)} --body {shlex.quote(body)} {'--draft' if draft else ''}",
    ]

    outputs = []
    for cmd in pipeline_cmds:
        res = await ctx.sandbox.exec(cmd, timeout=60)
        outputs.append(f"$ {cmd}\n{res.combined().strip()}")
        if res.exit_code != 0 and "commit" in cmd and "nothing to commit" in res.combined().lower():
            continue
        if res.exit_code != 0 and "gh pr create" not in cmd:
            return ToolResult.error(f"Command failed in pipeline:\n{res.combined()}")

    return ToolResult(
        content="\n\n".join(outputs),
        display={"kind": "pr_pipeline", "branch": clean_branch, "title": title},
    )


@registry.tool(
    "clean_gone_branches",
    "Prune and delete local Git branches that have been merged or deleted on the remote repository.",
    obj({}, []),
    permission="dangerous",
    group="git",
    mutating=True,
)
async def clean_gone_branches(ctx: ToolContext) -> ToolResult:
    cmd = "git fetch -p && git branch -vv | grep ': gone]' | awk '{print $1}' | xargs -r git branch -D"
    res = await ctx.sandbox.exec(cmd, timeout=30)
    output = res.combined().strip() or "No deleted remote branches to prune."
    return ToolResult(content=output)
