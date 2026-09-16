"""Skills engine: parsing, discovery, relevance, paste/URL/GitHub install paths."""

from __future__ import annotations

import pytest

from app.core.errors import AppError
from app.skills import manager as skills

VALID = """---
name: code-review
description: Review code for bugs and style. Use when reviewing pull requests.
version: 1.0.0
author: tester
tags:
  - review
---

# Code Review

Check everything twice.
"""


def _ws(tmp_path, name="ws") -> str:
    workspace = tmp_path / name
    (workspace / ".agent" / "skills").mkdir(parents=True)
    return str(workspace)


def test_parse_valid_skill():
    meta, body = skills.parse_skill_text(VALID)
    assert meta["name"] == "code-review"
    assert "Check everything" in body


def test_parse_rejects_bad_name():
    with pytest.raises(AppError):
        skills.parse_skill_text("---\nname: Bad Name!\ndescription: x\n---\nbody")


def test_parse_rejects_missing_description():
    with pytest.raises(AppError):
        skills.parse_skill_text("---\nname: ok-name\n---\nbody")


def test_discover_claude_dir_and_flat(tmp_path):
    workspace = _ws(tmp_path)
    root = tmp_path / "ws" / ".agent" / "skills"
    (root / "code-review").mkdir()
    (root / "code-review" / "SKILL.md").write_text(VALID, encoding="utf-8")
    (root / "notes.md").write_text("---\nname: notes\ndescription: Take notes.\n---\nHi", encoding="utf-8")

    found = {s.name: s for s in skills.discover_skills(workspace)}
    assert set(found) == {"code-review", "notes"}
    assert found["code-review"].source == "claude-dir"
    assert found["notes"].source == "flat"
    assert all(s.enabled for s in found.values())


def test_prompt_index_and_relevance(tmp_path):
    workspace = _ws(tmp_path)
    root = tmp_path / "ws" / ".agent" / "skills"
    (root / "code-review").mkdir()
    (root / "code-review" / "SKILL.md").write_text(VALID, encoding="utf-8")

    index = skills.build_skill_prompt(workspace, "")
    assert "code-review" in index
    assert "Check everything" not in index  # index only, progressive disclosure

    relevant = skills.build_skill_prompt(workspace, "please review my pull request carefully")
    assert "Check everything" in relevant  # full body auto-loaded

    unrelated = skills.build_skill_prompt(workspace, "what is the weather in paris")
    assert "Check everything" not in unrelated


def test_enable_disable_round_trip(tmp_path):
    workspace = _ws(tmp_path)
    skills.install_from_paste(workspace, "my-skill", "# Do things", hint="Does things")
    assert skills.set_skill_enabled(workspace, "my-skill", False).enabled is False
    assert "my-skill" not in [s.name for s in skills.discover_skills(workspace) if s.enabled]
    assert skills.set_skill_enabled(workspace, "my-skill", True).enabled is True


def test_paste_generates_frontmatter(tmp_path):
    workspace = _ws(tmp_path)
    installed = skills.install_from_paste(workspace, "My Cool Skill!", "# Steps\n1. Go")
    assert installed.name == "my-cool-skill"
    detail = skills.read_skill(workspace, "my-cool-skill")
    assert "Steps" in detail["body"]


def test_delete_skill(tmp_path):
    workspace = _ws(tmp_path)
    skills.install_from_paste(workspace, "temp-skill", "# x", hint="Temporary skill")
    skills.delete_skill(workspace, "temp-skill")
    assert "temp-skill" not in [s.name for s in skills.discover_skills(workspace)]
    with pytest.raises(AppError):
        skills.delete_skill(workspace, "temp-skill")


def test_install_from_url_raw_markdown(tmp_path, monkeypatch):
    workspace = _ws(tmp_path)

    def fake_fetch(url, limit=0):
        assert "SKILL.md" in url
        return VALID

    monkeypatch.setattr(skills, "_fetch_text", fake_fetch)
    installed = skills.install_from_url(workspace, "https://example.com/skills/code-review/SKILL.md")
    assert [s.name for s in installed] == ["code-review"]


def test_install_from_zip(tmp_path):
    import io
    import zipfile

    workspace = _ws(tmp_path)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("pack/my-skill/SKILL.md", VALID)
        zf.writestr("pack/my-skill/references/extra.md", "# extra")
        zf.writestr("../../evil.txt", "nope")  # zip-slip attempt
    installed = skills._install_from_zip_bytes(workspace, buf.getvalue(), origin="url")
    assert [s.name for s in installed] == ["code-review"]
    root = tmp_path / "ws" / ".agent" / "skills"
    assert (root / "code-review" / "references" / "extra.md").is_file()
    assert not (tmp_path / "evil.txt").exists()


def test_registry_normalize_shapes():
    npm_entry = {
        "server": {
            "name": "io.github.test/fs",
            "description": "FS tools",
            "repository": {"url": "https://github.com/test/fs"},
            "packages": [{"registryType": "npm", "identifier": "@test/fs", "version": "1.0.0"}],
            "remotes": [],
        },
        "version": "1.0.0",
    }
    normalized = skills_normalize(npm_entry)
    assert normalized["name"] == "io.github.test/fs"
    assert normalized["transports"] == ["stdio"]

    from app.mcp.registry import build_install_config

    config = build_install_config(npm_entry["server"])
    assert config["transport"] == "stdio"
    assert config["command"] == "npx"
    assert "@test/fs@1.0.0" in config["args"]

    remote_entry = {
        "server": {
            "name": "com.example/remote",
            "description": "Remote",
            "packages": [],
            "remotes": [{"type": "streamable-http", "url": "https://mcp.example.com/mcp"}],
        }
    }
    remote_config = build_install_config(remote_entry["server"])
    assert remote_config["transport"] == "http"
    assert remote_config["url"] == "https://mcp.example.com/mcp"


def skills_normalize(entry):
    from app.mcp.registry import normalize_entry

    return normalize_entry(entry)


def test_connector_services_have_builders():
    from app.connectors import SERVICES

    # AI model providers live in Settings → Models, never here.
    assert not (set(SERVICES) & {"openai", "anthropic", "groq", "deepseek", "openrouter"})
    assert len(SERVICES) >= 20
    for key, meta in SERVICES.items():
        assert meta.get("label"), key
        assert meta.get("build") or meta.get("client"), key
        assert meta.get("fields"), key
        assert meta.get("kind", "general") in ("general", "social"), key
        if meta.get("oauth"):
            assert meta["oauth"].get("authorize_url"), key
            assert meta["oauth"].get("token_url"), key
            assert meta["oauth"].get("scopes"), key


def test_oauth_authorize_url_shape():
    from app.connectors import build_authorize_url

    url, state = build_authorize_url(
        "github", client_id="cid", client_secret="sec",
        redirect_uri="https://app.example/api/v1/connectors/github/oauth/callback",
    )
    assert url.startswith("https://github.com/login/oauth/authorize?")
    assert "state=" in url and state in url
    assert "shh" not in url and "sec" not in url  # secret never in the URL

    # PKCE services embed a challenge
    pkce_url, _ = build_authorize_url(
        "twitter", client_id="cid", client_secret="sec",
        redirect_uri="https://app.example/cb",
    )
    assert "code_challenge=" in pkce_url


def test_marketplace_curated_have_raw_url(monkeypatch):
    """Every marketplace entry must carry a downloadable raw_url (regression:
    curated entries omitted it, so all marketplace installs failed).
    mcpservers.org entries install via GitHub instead, so they are exempt."""
    monkeypatch.setattr(skills, "_github_api", lambda *a, **k: [])
    monkeypatch.setattr(skills, "mso_listing", lambda q="": [])
    skills._marketplace_cache.update({"at": 9999999999.0, "items": []})
    try:
        items = skills.marketplace_live()
    finally:
        skills._marketplace_cache.update({"at": 0.0, "items": []})
    assert len(items) >= 8
    missing = [i["id"] for i in items if not i.get("raw_url")]
    assert not missing, f"entries without raw_url: {missing}"


def test_registry_detail_single_object_shape():
    """The registry versions/latest endpoint returns {"server": {...}}, not
    {"servers": [...]} — installs 404'd before this was handled."""
    from app.mcp.registry import _parse_detail

    single = {
        "server": {
            "name": "io.github.test/fs",
            "description": "FS tools",
            "version": "1.0.0",
            "packages": [{"registryType": "npm", "identifier": "@test/fs", "version": "1.0.0"}],
            "remotes": [],
        },
        "_meta": {},
    }
    detail = _parse_detail(single, "io.github.test/fs")
    assert detail["name"] == "io.github.test/fs"

    listed = {"servers": [single["server"]]}
    detail = _parse_detail(listed, "io.github.test/fs")
    assert detail["name"] == "io.github.test/fs"

    with pytest.raises(AppError):
        _parse_detail({"servers": []}, "io.github.test/fs")
    with pytest.raises(AppError):
        _parse_detail({}, "io.github.test/fs")


def test_extract_skill_mentions():
    names = {"code-review", "pdf"}
    assert skills.extract_skill_mentions("/code-review check this", names) == ["code-review"]
    assert skills.extract_skill_mentions("use /pdf and /code-review now", names) == ["pdf", "code-review"]
    assert skills.extract_skill_mentions("no mentions here", names) == []
    assert skills.extract_skill_mentions("/unknown-skill hi", names) == []
    assert skills.extract_skill_mentions("/PDF (caps) works", names) == ["pdf"]


def test_mentioned_skill_force_loaded(tmp_path):
    """An explicitly /mentioned skill loads its full body even when the rest
    of the text shares no keywords with it."""
    workspace = _ws(tmp_path)
    root = tmp_path / "ws" / ".agent" / "skills"
    (root / "code-review").mkdir()
    (root / "code-review" / "SKILL.md").write_text(VALID, encoding="utf-8")

    prompt = skills.build_skill_prompt(workspace, "/code-review xyzzy plugh qwerty")
    assert "Invoked Skills" in prompt
    assert "Check everything" in prompt

    auto = skills.build_skill_prompt(workspace, "xyzzy plugh qwerty")
    assert "Check everything" not in auto


def test_skill_prompt_with_meta_reports_names(tmp_path):
    workspace = _ws(tmp_path)
    root = tmp_path / "ws" / ".agent" / "skills"
    (root / "code-review").mkdir()
    (root / "code-review" / "SKILL.md").write_text(VALID, encoding="utf-8")

    prompt, invoked, auto = skills.skill_prompt_with_meta(workspace, "/code-review go")
    assert invoked == ["code-review"]
    assert "MANDATORY" in prompt

    prompt2, invoked2, auto2 = skills.skill_prompt_with_meta(workspace, "")
    assert invoked2 == [] and auto2 == []
    assert "code-review" in prompt2  # index always present


MSO_LISTING_HTML = """
<a href="/agent-skills/acme/cool-tool" class="group block h-full">
<div class="truncate text-sm font-semibold">Cool Tool</div>
<div data-slot="card-description" class="x">Does cool things fast.</div>
<span class="rounded-md border border-zinc-200">productivity</span>
</a>
<a href="/agent-skills/author/acme" class="x">Authors</a>
<a href="/agent-skills/category/dev" class="x">Dev</a>
"""

MSO_DETAIL_HTML = """
<h1>Cool Tool</h1>
<a href="https://github.com/acme/tools/tree/main/skills/cool-tool">GitHub</a>
"""


def test_mso_listing_parses_cards(monkeypatch):
    monkeypatch.setattr(skills, "_fetch_text", lambda url, limit=0: MSO_LISTING_HTML)
    skills._mso_cache.update({"at": 0.0, "items": []})
    try:
        items = skills.mso_listing()
    finally:
        skills._mso_cache.update({"at": 0.0, "items": []})
    assert len(items) == 1
    assert items[0]["id"] == "mso-acme-cool-tool"
    assert items[0]["author"] == "acme"
    assert items[0]["description"] == "Does cool things fast."
    assert "productivity" in items[0]["tags"]


def test_mso_github_spec_and_install(monkeypatch, tmp_path):
    def fake_fetch(url, limit=0):
        if url.rstrip("/").endswith("/agent-skills"):
            return MSO_LISTING_HTML
        if "mcpservers.org" in url:
            return MSO_DETAIL_HTML
        if url.endswith("SKILL.md"):
            return VALID
        raise AppError("unexpected fetch", code="fetch_failed")

    monkeypatch.setattr(skills, "_fetch_text", fake_fetch)
    monkeypatch.setattr(
        skills, "_github_tree_nodes",
        lambda owner, repo, ref: [
            {"type": "blob", "path": "skills/cool-tool/SKILL.md", "size": 100},
        ],
    )
    skills._mso_cache.update({"at": 0.0, "items": []})
    workspace = _ws(tmp_path)
    try:
        installed = skills.install_from_mso(workspace, "mso-acme-cool-tool")
    finally:
        skills._mso_cache.update({"at": 0.0, "items": []})
    assert installed.name == "code-review"


def test_registry_search_dedupes_versions(monkeypatch):
    import asyncio

    from app.mcp import registry as reg

    async def fake_get(path, params=None):
        item = lambda v: {
            "server": {"name": "x/dup", "description": "d", "packages": [], "remotes": []},
            "version": v,
        }
        return {"servers": [item("0.1.0"), item("0.2.0"), item("0.1.9")]}

    monkeypatch.setattr(reg, "_get", fake_get)
    reg._cache.clear()
    try:
        result = asyncio.run(reg.search_servers("", 30, 0))
    finally:
        reg._cache.clear()
    assert len(result["servers"]) == 1
    assert result["servers"][0]["version"] == "0.2.0"


def test_directory_parsing_unit():
    from app.mcp import directory as mso

    html = (
        '<a href="/remote-mcp-servers/neon" class="group flex">'
        '<div class="truncate text-sm font-semibold xyz">Neon</div>'
        '<div class="truncate text-xs abc">Postgres things</div></a>'
    )
    found = mso.CARD_RE.findall(html)
    assert found == [("neon", "Neon", "Postgres things")]
    detail_html = (
        "Connection details</h2><code class=\"x\">https://mcp.example.com/mcp</code>"
        "<dt class=\"y\">Transport</dt><dd class=\"z\">Streamable HTTP</dd>"
        "<dt class=\"y\">Authentication</dt><dd class=\"z\">API key</dd>"
    )
    section = detail_html.split("Connection details", 1)[1]
    assert mso.CODE_RE.search(section).group(1) == "https://mcp.example.com/mcp"
    fields = {k.lower(): v for k, v in mso.DT_RE.findall(section)}
    assert fields == {"transport": "Streamable HTTP", "authentication": "API key"}
    config = mso.build_install_config(
        {"slug": "neon", "endpoint": "https://mcp.example.com/mcp",
         "transport": "http", "transport_label": "Streamable HTTP", "auth": "API key"}
    )
    assert config["transport"] == "http"
    assert config["url"] == "https://mcp.example.com/mcp"
