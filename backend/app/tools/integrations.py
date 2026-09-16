"""Connector-backed tools: the agent can ship code, not just write it."""

from __future__ import annotations

import json
import shlex

from app.connectors import SERVICES, get_client
from app.core.utils import truncate
from app.db.session import SessionLocal
from app.tools.base import ToolContext, ToolResult, boolean, obj, string
from app.tools.registry import registry


async def _client(service: str):
    async with SessionLocal() as db:
        return await get_client(db, service)


@registry.tool(
    "connector_list",
    "List which external services (dev tools, social accounts, infra) are connected.",
    obj({}),
    group="integrations",
)
async def connector_list(ctx: ToolContext):
    lines = []
    for service in SERVICES:
        client = await _client(service)
        lines.append(f"- {SERVICES[service]['label']}: {'connected' if client else 'not connected'}")
    return ToolResult(content="\n".join(lines))


@registry.tool(
    "github",
    (
        "Call the GitHub API as the connected account. Actions: whoami, list_repos, create_repo, "
        "create_pull_request. Pass action arguments as a JSON object in `params`."
    ),
    obj(
        {
            "action": string(
                "Which call to make",
                enum=["whoami", "list_repos", "create_repo", "create_pull_request"],
            ),
            "params": string("JSON object of arguments for the action", default="{}"),
        },
        ["action"],
    ),
    permission="write",
    group="integrations",
    mutating=True,
)
async def github(ctx: ToolContext, action: str, params: str = "{}"):
    client = await _client("github")
    if not client:
        return ToolResult.error("GitHub is not connected. Add a token in Settings → Connectors.")
    try:
        kwargs = json.loads(params or "{}")
    except json.JSONDecodeError as exc:
        return ToolResult.error(f"params is not valid JSON: {exc}")
    method = getattr(client, action, None)
    if not callable(method):
        return ToolResult.error(f"unknown action: {action}")
    try:
        result = await method(**kwargs)
    except Exception as exc:
        return ToolResult.error(f"github.{action} failed: {exc}")
    return ToolResult(content=truncate(json.dumps(result, indent=2, default=str), 12_000))


@registry.tool(
    "github_push",
    (
        "Push the workspace repository to GitHub using the connected account's credentials. "
        "Creates the remote repo when it does not exist yet. When `repo` is omitted, the "
        "project's saved repo is reused (or `{login}/{project-slug}` on first push) and "
        "remembered on the project, so the repo identity stays the same everywhere."
    ),
    obj(
        {
            "repo": string("owner/name of the target repository (optional — defaults to the project's repo)", default=""),
            "branch": string("Branch to push", default="main"),
            "create_if_missing": boolean("Create the repo when absent", default=True),
            "private": boolean("Create it private", default=True),
        },
    ),
    permission="dangerous",
    group="integrations",
    mutating=True,
)
async def github_push(
    ctx: ToolContext, repo: str = "", branch: str = "main", create_if_missing: bool = True, private: bool = True
):
    from app.db.models import Project

    client = await _client("github")
    if not client:
        return ToolResult.error("GitHub is not connected. Add a token in Settings → Connectors.")

    target = (repo or "").strip()
    project_slug = ""
    if not target:
        async with SessionLocal() as db:
            project = await db.get(Project, ctx.project_id)
            if project is not None:
                target = (project.github_repo or "").strip()
                project_slug = (project.slug or "").strip() or ctx.project_id[:12]
        if not target:
            try:
                me = await client.whoami()
                login = str(me.get("login") or "").strip()
            except Exception:
                login = ""
            if not login:
                return ToolResult.error("Pass repo as owner/name, or connect GitHub first.")
            safe_slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in project_slug.lower()).strip("-") or "workspace"
            target = f"{login}/{safe_slug}"

    try:
        await client.request("GET", f"/repos/{target}")
    except Exception:
        if not create_if_missing:
            return ToolResult.error(f"repository {target} not found")
        name = target.split("/", 1)[-1]
        try:
            await client.create_repo(name, private=private)
        except Exception as exc:
            return ToolResult.error(f"could not create {target}: {exc}")

    remote = f"https://x-access-token:{client.token}@github.com/{target}.git"
    script = " && ".join([
        "git init -q 2>/dev/null || true",
        "git add -A",
        'git -c user.email=agent@rawal.local -c user.name="Rawal AI" commit -q -m "Update from Rawal AI" || true',
        f"git branch -M {shlex.quote(branch)}",
        f"git remote remove origin 2>/dev/null; git remote add origin {shlex.quote(remote)}",
        f"git push -u origin {shlex.quote(branch)} --force",
    ])
    res = await ctx.sandbox.exec(script, timeout=600)
    output = res.combined().replace(client.token, "***")
    if res.exit_code != 0:
        return ToolResult.error(f"push failed:\n{truncate(output, 4000)}")

    # Remember the repo on the project so every surface uses the same identity.
    try:
        async with SessionLocal() as db:
            project = await db.get(Project, ctx.project_id)
            if project is not None and project.github_repo != target:
                project.github_repo = target
                await db.commit()
    except Exception:
        pass
    return ToolResult(
        content=f"Pushed to https://github.com/{target} ({branch})\n{truncate(output, 3000)}",
        display={"kind": "link", "url": f"https://github.com/{target}", "label": target},
    )


@registry.tool(
    "vercel",
    "Call the Vercel API. Actions: whoami, list_projects, list_deployments.",
    obj(
        {
            "action": string("Which call to make", enum=["whoami", "list_projects", "list_deployments"]),
            "params": string("JSON object of arguments", default="{}"),
        },
        ["action"],
    ),
    group="integrations",
)
async def vercel(ctx: ToolContext, action: str, params: str = "{}"):
    return await _generic("vercel", action, params)


@registry.tool(
    "render",
    "Call the Render API. Actions: whoami, list_services, deploy.",
    obj(
        {
            "action": string("Which call to make", enum=["whoami", "list_services", "deploy"]),
            "params": string("JSON object of arguments", default="{}"),
        },
        ["action"],
    ),
    permission="write",
    group="integrations",
    mutating=True,
)
async def render(ctx: ToolContext, action: str, params: str = "{}"):
    return await _generic("render", action, params)


@registry.tool(
    "huggingface",
    "Call the Hugging Face API. Actions: whoami, list_spaces.",
    obj(
        {
            "action": string("Which call to make", enum=["whoami", "list_spaces"]),
            "params": string("JSON object of arguments", default="{}"),
        },
        ["action"],
    ),
    group="integrations",
)
async def huggingface(ctx: ToolContext, action: str, params: str = "{}"):
    return await _generic("huggingface", action, params)


async def _generic(service: str, action: str, params: str) -> ToolResult:
    client = await _client(service)
    if not client:
        return ToolResult.error(f"{service} is not connected. Add a token in Settings → Connectors.")
    try:
        kwargs = json.loads(params or "{}")
    except json.JSONDecodeError as exc:
        return ToolResult.error(f"params is not valid JSON: {exc}")
    method = getattr(client, action, None)
    if not callable(method):
        return ToolResult.error(f"unknown action: {action}")
    try:
        result = await method(**kwargs)
    except Exception as exc:
        return ToolResult.error(f"{service}.{action} failed: {exc}")
    return ToolResult(content=truncate(json.dumps(result, indent=2, default=str), 12_000))


@registry.tool(
    "social",
    (
        "Act through a connected social/messaging account. "
        "telegram.send_message(chat_id, text); discord.create_message(channel_id, content); "
        "slack.post_message(channel, text); twitter.create_tweet(text); "
        "facebook.list_pages(); whatsapp.send_text(to, body). "
        "Pass action arguments as a JSON object in `params`. "
        "Posting is real — confirm the destination with the user first."
    ),
    obj(
        {
            "service": string(
                "Social account to use",
                enum=[
                    "telegram", "discord", "slack", "twitter", "facebook",
                    "instagram", "whatsapp", "linkedin", "youtube", "tiktok",
                ],
            ),
            "action": string("Which call to make"),
            "params": string("JSON object of arguments for the action", default="{}"),
        },
        ["service", "action"],
    ),
    permission="write",
    group="integrations",
    mutating=True,
)
async def social(ctx: ToolContext, service: str, action: str, params: str = "{}"):
    if service == "instagram":
        return ToolResult.error(
            "Instagram has no direct post API here — publish via the linked Facebook Page instead."
        )
    return await _generic(service, action, params)
