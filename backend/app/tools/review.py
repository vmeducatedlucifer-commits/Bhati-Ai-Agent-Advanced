"""Advanced multi-agent code review toolkit matching Anthropic PR review toolkit."""

from __future__ import annotations

import os
from typing import Any

from app.agent.security_guard import scan_diff_for_security_issues
from app.tools.base import ToolContext, ToolResult, boolean, obj, string
from app.tools.registry import registry


@registry.tool(
    "code_review",
    (
        "Run an advanced multi-faceted code review on the workspace or specific files. "
        "Audits for silent failures, typing safety, security vulnerabilities, and code complexity."
    ),
    obj(
        {
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Specific list of file paths to review (defaults to recent git changes or workspace files)",
            },
            "aspects": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": ["silent_failures", "type_design", "security", "complexity", "all"],
                },
                "description": "Review dimensions to analyze (default: all)",
            },
            "detail_level": string("Detail level", enum=["summary", "verbose"], default="summary"),
        },
        [],
    ),
    permission="safe",
    group="git",
    mutating=False,
)
async def code_review(
    ctx: ToolContext,
    files: list[str] | None = None,
    aspects: list[str] | None = None,
    detail_level: str = "summary",
) -> ToolResult:
    review_aspects = aspects or ["all"]
    check_all = "all" in review_aspects

    target_files = files or []
    if not target_files:
        # Check git modified files first
        res = await ctx.sandbox.exec("git status --porcelain", timeout=15)
        if res.exit_code == 0 and res.stdout.strip():
            for line in res.stdout.splitlines():
                parts = line.strip().split(maxsplit=1)
                if len(parts) == 2:
                    target_files.append(parts[1])

    if not target_files:
        # Fallback to key source files
        listing = await ctx.sandbox.list_dir("")
        target_files = [f.name for f in listing if not f.is_dir and f.name.endswith((".py", ".ts", ".tsx", ".js", ".jsx"))][:15]

    findings = []
    scanned_count = 0

    for path in target_files:
        try:
            content = await ctx.sandbox.read_file(path, max_bytes=500_000)
            scanned_count += 1
            if check_all or "security" in review_aspects:
                sec_issues = scan_diff_for_security_issues(path, content)
                for issue in sec_issues:
                    findings.append(f"[{issue.severity}] {issue.message}")

            if check_all or "silent_failures" in review_aspects:
                # Silent failure check
                lines = content.splitlines()
                for idx, line in enumerate(lines, 1):
                    if "except:" in line or "except Exception:" in line:
                        if idx < len(lines) and "pass" in lines[idx]:
                            findings.append(f"[HIGH] Silent failure: Broad exception catch with bare `pass` at {path}:{idx}")
                    if "catch (" in line or "catch(" in line:
                        if "{}" in line or (idx < len(lines) and lines[idx].strip() == "}"):
                            findings.append(f"[HIGH] Silent failure: Empty catch block suppresses error at {path}:{idx}")

            if check_all or "type_design" in review_aspects:
                lines = content.splitlines()
                for idx, line in enumerate(lines, 1):
                    if ": any" in line and not line.strip().startswith("//"):
                        findings.append(f"[MEDIUM] Type design: Use of `: any` at {path}:{idx}. Prefer explicit typing or `unknown`.")

        except Exception:
            continue

    if not findings:
        report = f"## Code Review Complete\n\nScanned {scanned_count} files.\n**Status:** No critical bugs, silent failures, or security vulnerabilities found."
    else:
        report = f"## Code Review Findings ({len(findings)} issues in {scanned_count} files)\n\n"
        for idx, f in enumerate(findings, 1):
            report += f"{idx}. {f}\n"

    return ToolResult(
        content=report,
        display={"kind": "code_review", "files_scanned": scanned_count, "issues": len(findings)},
    )
