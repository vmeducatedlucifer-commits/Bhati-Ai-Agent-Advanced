"""Shell execution inside the sandbox, streamed to the UI terminal."""

from __future__ import annotations

import shlex

from app.core.config import settings
from app.core.utils import truncate
from app.tools.base import ToolContext, ToolResult, boolean, integer, obj, string
from app.tools.registry import registry

MAX_OUTPUT_CHARS = 30_000

BANNED = (
    "rm -rf /",
    "rm -r -f /",
    "rm -rf /*",
    "mkfs",
    ":(){:|:&};:",
    "> /dev/sda",
    "> /dev/nvme",
    "dd if=/dev/zero of=/dev",
    "chmod -r 777 /",
    "chown -r root /",
)


def _is_banned(command: str) -> str | None:
    lowered = " ".join(command.lower().split())
    for pattern in BANNED:
        if pattern in lowered:
            return pattern
    return None


@registry.tool(
    "bash",
    (
        "Run a shell command inside the sandbox and return its output. The sandbox is a "
        "Linux container with the workspace mounted at the current directory. Use this for "
        "builds, tests, package installs and any CLI. Output streams to the user's terminal live."
    ),
    obj(
        {
            "command": string("Shell command to run"),
            "cwd": string("Working directory relative to the workspace root", default=""),
            "timeout": integer("Seconds before the command is killed", default=settings.SANDBOX_COMMAND_TIMEOUT_S),
            "description": string("Short human-readable label shown in the UI", default=""),
        },
        ["command"],
    ),
    permission="dangerous",
    group="shell",
    mutating=True,
)
async def bash(
    ctx: ToolContext,
    command: str,
    cwd: str = "",
    timeout: int = settings.SANDBOX_COMMAND_TIMEOUT_S,
    description: str = "",
):
    if banned := _is_banned(command):
        return ToolResult.error(f"refusing to run a command containing `{banned}`")

    await ctx.emit(
        "terminal_start",
        {"tool_call_id": ctx.tool_call_id, "command": command, "cwd": cwd, "label": description},
    )

    # Detect heavy commands that would crash Render's 512MB limit
    clwd = command.lower()
    is_heavy = any(x in clwd for x in ["npm install", "yarn install", "pnpm install", "npm run build", "pip install", "docker build", "cargo build"])

    from app.storage.github import github_manager

    # Offload heavy tasks to GitHub Actions if GitHub Token is linked
    if is_heavy and await github_manager.is_enabled():
        async def on_chunk(chunk: str):
            await ctx.emit("terminal_output", {"tool_call_id": ctx.tool_call_id, "chunk": chunk})

        res = await github_manager.run_in_github_actions(
            project_id=ctx.project_id,
            workspace_path=ctx.workspace,
            command=f"cd {shlex.quote(cwd or '.')} && {command}",
            on_chunk=on_chunk
        )

        await ctx.emit("terminal_end", {"tool_call_id": ctx.tool_call_id, "exit_code": res["exit_code"]})
        body = truncate(res["output"].strip(), MAX_OUTPUT_CHARS) or "(no output)"
        return ToolResult(
            content=f"$ {command}\n{body}\n\nGitHub Actions Job: {res.get('url', '')}",
            display={"kind": "terminal", "command": command, "output": res["output"], "cwd": cwd},
        )

    # Local fallback
    buffer: list[str] = []
    total = 0
    try:
        async for chunk in ctx.sandbox.exec_stream(command, cwd=cwd or None, timeout=timeout):
            total += len(chunk)
            if total <= MAX_OUTPUT_CHARS * 2:
                buffer.append(chunk)
            await ctx.emit("terminal_output", {"tool_call_id": ctx.tool_call_id, "chunk": chunk})
    except Exception as exc:
        await ctx.emit("terminal_end", {"tool_call_id": ctx.tool_call_id, "exit_code": -1})
        return ToolResult.error(f"command failed to start: {exc}")

    output = "".join(buffer)
    # Streaming does not surface an exit code; probe the shell's last exit status.
    probe = await ctx.sandbox.exec("echo $?", timeout=10)
    exit_code = 0
    try:
        exit_code = int(probe.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        pass
    await ctx.emit("terminal_end", {"tool_call_id": ctx.tool_call_id, "exit_code": exit_code})

    body = truncate(output.strip(), MAX_OUTPUT_CHARS) or "(no output)"
    return ToolResult(
        content=f"$ {command}\n{body}",
        display={"kind": "terminal", "command": command, "output": output, "cwd": cwd},
    )


@registry.tool(
    "bash_output",
    "Check the exit status of a command by re-running it quietly. Useful for `test -f`, `which`, etc.",
    obj({"command": string("Command to probe")}, ["command"]),
    group="shell",
)
async def bash_output(ctx: ToolContext, command: str):
    if banned := _is_banned(command):
        return ToolResult.error(f"refusing to run a command containing `{banned}`")
    res = await ctx.sandbox.exec(command, timeout=60)
    return ToolResult(
        content=f"exit={res.exit_code}\n{truncate(res.combined(), 8000)}",
        display={"kind": "terminal", "command": command, "output": res.combined()},
    )


@registry.tool(
    "install_packages",
    "Install system or language packages in the sandbox (apt, pip, npm).",
    obj(
        {
            "manager": string("Package manager", enum=["apt", "pip", "npm", "npx"]),
            "packages": string("Space-separated package names"),
            "dev": boolean("Install as dev dependency (npm only)", default=False),
        },
        ["manager", "packages"],
    ),
    permission="dangerous",
    group="shell",
    mutating=True,
)
async def install_packages(ctx: ToolContext, manager: str, packages: str, dev: bool = False):
    commands = {
        "apt": f"apt-get update -qq && apt-get install -y -qq --no-install-recommends {packages}",
        "pip": f"pip install --no-cache-dir -q {packages}",
        "npm": f"npm install {'--save-dev' if dev else ''} {packages}",
        "npx": f"npx -y {packages}",
    }
    if manager not in commands:
        return ToolResult.error(f"unsupported manager: {manager}")
    return await bash(ctx, commands[manager], timeout=900, description=f"install {packages}")
