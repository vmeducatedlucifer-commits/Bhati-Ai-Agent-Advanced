"""Claude-style Structured Memory System.

Stores memories as structured markdown files with YAML frontmatter inside `.agent/memory/`,
indexed by a top-level `MEMORY.md` loaded into every session prompt.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.core.logging import get_logger
from app.tools.base import ToolContext, ToolResult, obj, string
from app.tools.registry import registry

log = get_logger("app.agent.memory")

MEMORY_DIR_NAME = ".agent/memory"
MEMORY_INDEX_FILE = ".agent/MEMORY.md"


def get_memory_dir(workspace_path: str) -> Path:
    mem_dir = Path(workspace_path) / MEMORY_DIR_NAME
    mem_dir.mkdir(parents=True, exist_ok=True)
    return mem_dir


def get_memory_index(workspace_path: str) -> Path:
    index_file = Path(workspace_path) / MEMORY_INDEX_FILE
    index_file.parent.mkdir(parents=True, exist_ok=True)
    return index_file


def load_project_memory_prompt(workspace_path: str) -> str:
    """Load the MEMORY.md index content into the agent's context window."""
    index_file = get_memory_index(workspace_path)
    if not index_file.exists():
        return ""

    try:
        content = index_file.read_text(encoding="utf-8").strip()
        if not content:
            return ""
        return f"## Project Persistent Memory (MEMORY.md)\n\n{content}"
    except Exception as exc:
        log.warning("Could not load MEMORY.md: %s", exc)
        return ""


SKILLS_DIR_NAME = ".agent/skills"


def load_skill_packs(workspace_path: str, user_text: str = "") -> str:
    """Skill index + auto-loaded relevant bodies (delegates to app.skills)."""
    from app.skills.manager import build_skill_prompt

    try:
        return build_skill_prompt(workspace_path, user_text)
    except Exception as exc:
        log.warning("Could not load skills: %s", exc)
        return ""


def load_skill_packs_with_meta(
    workspace_path: str, user_text: str = ""
) -> tuple[str, list[str], list[str]]:
    """Like load_skill_packs, but also returns (invoked, auto) skill names."""
    from app.skills.manager import skill_prompt_with_meta

    try:
        return skill_prompt_with_meta(workspace_path, user_text)
    except Exception as exc:
        log.warning("Could not load skills: %s", exc)
        return "", [], []


@registry.tool(
    "remember",
    (
        "Save a durable project fact, user preference, or architectural rule to permanent markdown memory. "
        "Creates a structured `.md` file in `.agent/memory/` and updates `.agent/MEMORY.md`."
    ),
    obj(
        {
            "name": string("Short kebab-case slug for the memory, e.g. 'auth-jwt-format' or 'use-tailwind'"),
            "description": string("One-line summary of what this memory records"),
            "fact": string("The detailed knowledge, constraint, or preference to remember"),
            "type": string("Category of memory", enum=["user", "feedback", "project", "reference"], default="project"),
        },
        ["name", "description", "fact"],
    ),
    permission="write",
    group="memory",
    mutating=True,
)
async def remember(
    ctx: ToolContext,
    name: str,
    description: str,
    fact: str,
    type: str = "project",
):
    clean_name = re.sub(r"[^a-zA-Z0-9_-]", "-", name).strip("-").lower()
    if not clean_name:
        return ToolResult.error("Invalid memory name")

    mem_dir = get_memory_dir(ctx.workspace)
    mem_file = mem_dir / f"{clean_name}.md"

    # Format structured Markdown with YAML frontmatter
    file_content = f"""---
name: {clean_name}
description: {description}
metadata:
  type: {type}
---

{fact}
"""
    try:
        mem_file.write_text(file_content, encoding="utf-8")
    except Exception as exc:
        return ToolResult.error(f"Failed to write memory file: {exc}")

    # Rebuild / Update MEMORY.md index
    index_file = get_memory_index(ctx.workspace)
    try:
        entries = []
        for file in sorted(mem_dir.glob("*.md")):
            text = file.read_text(encoding="utf-8", errors="ignore")
            desc_match = re.search(r"description:\s*(.+)", text)
            desc = desc_match.group(1).strip() if desc_match else file.stem
            entries.append(f"- [{file.stem}]({file.name}) — {desc}")

        index_content = "# Project Memory Index\n\n" + "\n".join(entries) + "\n"
        index_file.write_text(index_content, encoding="utf-8")
    except Exception as exc:
        log.warning("Failed to update MEMORY.md: %s", exc)

    return ToolResult(
        content=f"Saved memory `{clean_name}` to `.agent/memory/{clean_name}.md` and updated `MEMORY.md`.",
        display={"kind": "memory", "name": clean_name, "description": description, "type": type},
    )


@registry.tool(
    "recall",
    "Read a specific memory file from `.agent/memory/` by name.",
    obj({"name": string("Memory slug or filename to read")}, ["name"]),
    group="memory",
)
async def recall(ctx: ToolContext, name: str):
    clean_name = name.replace(".md", "").strip().lower()
    mem_file = get_memory_dir(ctx.workspace) / f"{clean_name}.md"

    if not mem_file.exists():
        return ToolResult.error(f"Memory `{clean_name}` not found in `.agent/memory/`.")

    try:
        content = mem_file.read_text(encoding="utf-8")
        return ToolResult(content=f"Memory `{clean_name}`:\n\n{content}")
    except Exception as exc:
        return ToolResult.error(f"Failed to read memory: {exc}")
