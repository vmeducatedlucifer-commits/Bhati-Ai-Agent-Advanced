"""Agent Skills engine (Agent Skills spec compatible).

Skills live in `<workspace>/.agent/skills/` in either layout:
  .agent/skills/<slug>/SKILL.md          # Claude / OpenClaw / agentskills.io format
  .agent/skills/<slug>.md                # legacy flat file

Discovery is progressive-disclosure style: the prompt always carries the
compact name+description index, and full SKILL.md bodies auto-load only when
relevant to the user's turn.
"""

from app.skills.manager import (
    MARKETPLACE,
    InstalledSkill,
    browse_github_repo,
    build_skill_prompt,
    delete_skill,
    discover_skills,
    extract_skill_mentions,
    install_from_github,
    install_from_marketplace,
    install_from_paste,
    install_from_url,
    parse_skill_text,
    read_skill,
    set_skill_enabled,
    skill_prompt_with_meta,
)

__all__ = [
    "MARKETPLACE",
    "InstalledSkill",
    "browse_github_repo",
    "build_skill_prompt",
    "delete_skill",
    "discover_skills",
    "extract_skill_mentions",
    "install_from_github",
    "install_from_marketplace",
    "install_from_paste",
    "install_from_url",
    "parse_skill_text",
    "read_skill",
    "set_skill_enabled",
    "skill_prompt_with_meta",
]
