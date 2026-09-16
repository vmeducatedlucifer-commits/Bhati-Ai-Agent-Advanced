"""Hook Architecture — uncensored.

Pre-tool never blocks. High-risk commands are logged only.
Post-tool still does syntax checks and optional GitHub sync.
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.tools.base import Tool, ToolContext, ToolResult

log = get_logger("app.agent.hooks")

# Hard blocks permanently disabled.
DANGEROUS_BASH_PATTERNS: list[tuple[str, str]] = []


class HookEngine:
    @staticmethod
    async def pre_tool_hook(tool: Tool, ctx: ToolContext, arguments: dict[str, Any]) -> str | None:
        """Never blocks. Logs high-risk patterns for audit only."""
        if tool.name == "bash":
            cmd = str(arguments.get("command", "")).strip()
            risky_markers = ("rm -rf /", "mkfs", "dd if=", "shutdown", "reboot", ":(){", "curl|sh", "wget|sh")
            lower = cmd.lower().replace(" ", "")
            for marker in risky_markers:
                if marker.replace(" ", "") in lower or marker in cmd.lower():
                    log.warning("PreToolHook (uncensored): high-risk command observed: %s", cmd[:240])
                    break
        return None  # always allow

    @staticmethod
    async def post_tool_hook(tool: Tool, ctx: ToolContext, result: ToolResult) -> ToolResult:
        if tool.name in ("write_file", "edit_file", "bash") and not result.is_error:
            try:
                import asyncio

                from app.storage.github import github_manager
                if await github_manager.is_enabled():
                    asyncio.create_task(
                        github_manager.sync_workspace(
                            project_id=ctx.project_id,
                            workspace_path=ctx.workspace,
                        )
                    )
            except Exception:
                pass

        if tool.name in ("write_file", "edit_file") and not result.is_error:
            path = str(result.display.get("path") or "")
            if path.endswith((".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".md", ".html", ".css")):
                try:
                    if path.endswith(".py"):
                        import shlex
                        test_syntax = await ctx.sandbox.exec(
                            f"python3 -m py_compile {shlex.quote(path)} 2>&1", timeout=10
                        )
                        if test_syntax.exit_code != 0 and "SyntaxError" in test_syntax.stdout:
                            log.warning("PostToolHook syntax error in %s: %s", path, test_syntax.stdout)
                            result.content += f"\n\nNote: Syntax verification warning:\n{test_syntax.stdout.strip()[:300]}"
                except Exception:
                    pass

        return result


hooks = HookEngine()
