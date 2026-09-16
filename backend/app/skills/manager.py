"""Agent Skills engine: discovery, relevance auto-load, and installers.

Implements the Agent Skills spec subset shared by Claude Code, OpenClaw and
agentskills.io: `<slug>/SKILL.md` with YAML frontmatter (`name`,
`description`, plus optional `version`/`author`/`license`/`tags`/`model`/
`allowed-tools`/invocation flags), optional `scripts/`/`references/`/`assets/`.
Legacy flat `<slug>.md` files keep working.
"""

from __future__ import annotations

import io
import json
import re
import shutil
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import yaml

from app.core.config import settings
from app.core.errors import AppError
from app.core.logging import get_logger

log = get_logger("app.skills")

SKILLS_DIR_NAME = ".agent/skills"
STATE_FILE_NAME = ".agent/skills.json"
MAX_DEPTH = 3
FETCH_LIMIT_BYTES = 2_000_000
ZIP_LIMIT_BYTES = 50_000_000
RELEVANCE_BUDGET_CHARS = 12_000
MAX_AUTO_SKILLS = 4

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
STOPWORDS = frozenset(
    "the a an and or for with this that from have has are was were will would can could should "
    "what when where which while withing about into over under your you your we our they them his her its "
    "there their then than also just like make made using use used via per please tell show give get got do does did don".split()
)


@dataclass
class InstalledSkill:
    name: str
    description: str
    version: str = ""
    author: str = ""
    tags: list[str] = field(default_factory=list)
    source: str = "claude-dir"  # claude-dir | flat | github | marketplace | paste | url
    path: str = ""  # workspace-relative
    files: list[str] = field(default_factory=list)
    enabled: bool = True
    origin_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "tags": self.tags,
            "source": self.source,
            "path": self.path,
            "files": self.files,
            "enabled": self.enabled,
            "origin_url": self.origin_url,
        }


# ---------------------------------------------------------------- parsing ---


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split `---` YAML frontmatter from the markdown body."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw = text[3:end].strip()
    try:
        meta = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise AppError(f"Invalid YAML frontmatter: {exc}", code="bad_skill") from exc
    if not isinstance(meta, dict):
        raise AppError("Skill frontmatter must be a mapping", code="bad_skill")
    return meta, text[end + 4 :].lstrip("\n")


def parse_skill_text(text: str) -> tuple[dict[str, Any], str]:
    meta, body = split_frontmatter(text)
    name = str(meta.get("name", "")).strip()
    description = str(meta.get("description", "")).strip()
    problems: list[str] = []
    if not name or not NAME_RE.match(name):
        problems.append("name must be 1-64 chars of lowercase letters, numbers and hyphens")
    if not description:
        problems.append("description is required (what it does + when to use it)")
    elif len(description) > 1024:
        problems.append("description must be 1024 chars or fewer")
    if problems:
        raise AppError("Invalid skill: " + "; ".join(problems), code="bad_skill")
    return meta, body


def ensure_frontmatter(name: str, hint: str, content: str) -> str:
    """Wrap pasted markdown lacking frontmatter in a valid header."""
    meta, _ = split_frontmatter(content)
    if meta.get("name") and meta.get("description"):
        return content
    desc = (hint or f"User-provided skill {name}").strip().replace("\n", " ")[:200]
    header = "---\n" + yaml.safe_dump(
        {"name": name, "description": desc}, sort_keys=False, allow_unicode=True
    ) + "---\n\n"
    # Strip a broken header if present so we don't double it.
    if content.startswith("---"):
        _, body = split_frontmatter(content) if "\n---" in content else ({}, content)
        return header + body
    return header + content


def slugify_skill(raw: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    if not slug or not NAME_RE.match(slug):
        raise AppError(f"Cannot derive a valid skill name from {raw!r}", code="bad_skill")
    return slug[:64]


# --------------------------------------------------------------- discovery ---


def _skills_root(workspace: str) -> Path:
    root = Path(workspace) / SKILLS_DIR_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def _load_state(root: Path) -> dict[str, Any]:
    state_file = root.parent / "skills.json"
    try:
        return json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(root: Path, state: dict[str, Any]) -> None:
    (root.parent / "skills.json").write_text(json.dumps(state, indent=2), encoding="utf-8")


def discover_skills(workspace: str) -> list[InstalledSkill]:
    """Find every installable skill under the workspace skills dir."""
    root = _skills_root(workspace)
    state = _load_state(root)
    disabled = set(state.get("disabled", []))
    origins = state.get("origins", {})

    found: dict[str, InstalledSkill] = {}

    # Claude-style directories: <slug>/SKILL.md (nested up to MAX_DEPTH).
    candidates: list[tuple[Path, int]] = [(root, 0)]
    while candidates:
        directory, depth = candidates.pop()
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir() and depth < MAX_DEPTH:
                skill_file = entry / "SKILL.md"
                alt = entry / "skill.md"
                if skill_file.is_file():
                    _register_skill_file(skill_file, root, found, disabled, origins, "claude-dir")
                elif alt.is_file():
                    _register_skill_file(alt, root, found, disabled, origins, "claude-dir")
                else:
                    candidates.append((entry, depth + 1))
            elif entry.is_file() and depth == 0 and entry.suffix.lower() == ".md":
                _register_skill_file(entry, root, found, disabled, origins, "flat")

    return sorted(found.values(), key=lambda s: s.name)


def _register_skill_file(
    path: Path,
    root: Path,
    found: dict[str, InstalledSkill],
    disabled: set[str],
    origins: dict[str, str],
    fallback_source: str,
) -> None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        meta, _ = parse_skill_text(text)
    except (AppError, OSError) as exc:
        log.warning("skipping invalid skill %s: %s", path, exc)
        return
    name = str(meta["name"])
    if name in found:
        return
    rel_dir = path.parent.relative_to(root)
    files: list[str] = []
    if path.name.lower() == "skill.md":
        try:
            files = sorted(
                str(p.relative_to(path.parent))
                for p in path.parent.rglob("*")
                if p.is_file() and len(files) < 200
            )
        except OSError:
            files = [path.name]
    tags = meta.get("tags") or []
    found[name] = InstalledSkill(
        name=name,
        description=str(meta.get("description", ""))[:300],
        version=str(meta.get("version", "")),
        author=str(meta.get("author", "")),
        tags=[str(t) for t in tags] if isinstance(tags, list) else [],
        source=origins.get(name, fallback_source),
        path=str(path.relative_to(root.parent.parent))
        if _is_within(path, root.parent.parent)
        else path.name,
        files=files,
        enabled=name not in disabled,
        origin_url=str(origins.get(f"{name}:url", "")),
    )


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def read_skill(workspace: str, name: str) -> dict[str, Any]:
    for skill in discover_skills(workspace):
        if skill.name == name:
            root = _skills_root(workspace)
            target = (root.parent.parent / skill.path).resolve() if skill.path else None
            body = ""
            if target and target.is_file() and _is_within(target, root):
                body = target.read_text(encoding="utf-8", errors="ignore")
            return {**skill.to_dict(), "body": body}
    raise AppError(f"Skill not found: {name}", code="not_found", status_code=404)


# ----------------------------------------------------------------- prompting ---


def _keywords(text: str) -> set[str]:
    return {
        w for w in re.findall(r"[a-z0-9]{4,}", text.lower()) if w not in STOPWORDS
    }


MENTION_RE = re.compile(r"(?:^|\s)/([a-z0-9][a-z0-9-]{0,63})")


def extract_skill_mentions(user_text: str, names: set[str]) -> list[str]:
    """Explicit `/skill-name` invocations in the user's turn, in order."""
    seen: list[str] = []
    for match in MENTION_RE.findall(user_text.lower()):
        if match in names and match not in seen:
            seen.append(match)
    return seen


def _load_skill_body(workspace: str, name: str) -> str:
    try:
        return str(read_skill(workspace, name).get("body", ""))
    except AppError:
        return ""


def skill_prompt_with_meta(
    workspace: str, user_text: str = ""
) -> tuple[str, list[str], list[str]]:
    """Like build_skill_prompt, but also returns (invoked, auto) skill names.

    `invoked` = explicitly /mentioned by the user (always loaded first and
    mandatory for the agent to follow); `auto` = relevance-loaded.
    """
    skills = [s for s in discover_skills(workspace) if s.enabled]
    if not skills:
        return "", [], []

    index = "\n".join(f"- {s.name}: {s.description}" for s in skills)
    prompt = f"## Available Skills (invoke with /name when relevant)\n\n{index}"

    bodies: list[str] = []
    invoked: list[str] = []
    auto: list[str] = []
    used = 0

    def take(name: str, bucket: list[str]) -> None:
        nonlocal used
        body = _load_skill_body(workspace, name)[:RELEVANCE_BUDGET_CHARS]
        if not body or used + len(body) > RELEVANCE_BUDGET_CHARS:
            return
        used += len(body)
        bodies.append(f"### Skill: {name}\n\n{body}")
        bucket.append(name)

    # Explicit mentions first: the user picked these, so their full
    # instructions always load, ahead of anything merely relevant.
    by_name = {s.name: s for s in skills}
    mentioned = extract_skill_mentions(user_text, set(by_name))
    for name in mentioned:
        take(name, invoked)
    if invoked:
        prompt += (
            "\n\n## Invoked Skills (MANDATORY — the user explicitly invoked "
            "these with /name for this turn. Follow them exactly, from the "
            "first step: apply their workflow, use their scripts and formats, "
            "and do not skip, summarize away, or substitute your own process.)"
            "\n\n" + "\n\n".join(bodies)
        )
        bodies_before_relevant = len(bodies)
    else:
        bodies_before_relevant = 0

    if user_text.strip():
        # Relevance auto-load: keyword overlap between turn and name+description.
        query = _keywords(user_text)
        if query:
            scored: list[tuple[int, InstalledSkill]] = []
            for skill in skills:
                hay = _keywords(f"{skill.name} {skill.description} {' '.join(skill.tags)}")
                overlap = len(query & hay)
                # Name hits weigh more (explicit /name invocation or direct mention).
                for token in query:
                    if token in skill.name.replace("-", " "):
                        overlap += 2
                if overlap > 0:
                    scored.append((overlap, skill))
            scored.sort(key=lambda item: -item[0])

            mentioned_set = set(mentioned)
            for _, skill in scored[:MAX_AUTO_SKILLS]:
                if skill.name in mentioned_set:
                    continue  # already loaded above as explicitly invoked
                take(skill.name, auto)

    if len(bodies) > bodies_before_relevant:
        prompt += (
            "\n\n## Relevant Skill Instructions (auto-loaded)\n\n"
            + "\n\n".join(bodies[bodies_before_relevant:])
        )
    return prompt, invoked, auto


def build_skill_prompt(workspace: str, user_text: str = "") -> str:
    """Compact index of all enabled skills + full bodies of relevant ones."""
    prompt, _, _ = skill_prompt_with_meta(workspace, user_text)
    return prompt


# ----------------------------------------------------------------- install ---


def write_skill(workspace: str, slug: str, skill_md: str, origin: str = "", origin_url: str = "") -> InstalledSkill:
    slug = slugify_skill(slug)
    meta, _ = parse_skill_text(skill_md)
    if str(meta.get("name")) != slug:
        raise AppError(
            f"Frontmatter name {meta.get('name')!r} must match the skill slug {slug!r}",
            code="bad_skill",
        )
    root = _skills_root(workspace)
    target_dir = (root / slug).resolve()
    if target_dir != root.resolve() and root.resolve() not in target_dir.parents:
        raise AppError("Invalid skill path", code="bad_skill")
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")

    state = _load_state(root)
    origins = state.setdefault("origins", {})
    origins[slug] = origin or "paste"
    if origin_url:
        origins[f"{slug}:url"] = origin_url
    state.get("disabled", []).remove(slug) if slug in state.get("disabled", []) else None
    _save_state(root, state)
    log.info("installed skill %s from %s", slug, origin or "paste")
    for skill in discover_skills(workspace):
        if skill.name == slug:
            return skill
    raise AppError("Install succeeded but skill not found", code="internal")


def install_from_paste(workspace: str, name: str, content: str, hint: str = "") -> InstalledSkill:
    slug = slugify_skill(name)
    return write_skill(workspace, slug, ensure_frontmatter(slug, hint, content), origin="paste")


def _github_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "BhatiAiAgent/2.0"}
    if settings.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"
    return headers


def _fetch_text(url: str, limit: int = FETCH_LIMIT_BYTES) -> str:
    if not url.startswith(("https://", "http://")):
        raise AppError("Only http(s) URLs are supported", code="bad_url")
    from urllib.parse import urljoin as _urljoin

    from app.core.net import assert_public_url

    assert_public_url(url)
    try:
        current = url
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            for _ in range(6):
                with client.stream("GET", current, headers={"User-Agent": "BhatiAiAgent/2.0"}) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location", "")
                        if not location:
                            raise AppError("Redirect without location", code="fetch_failed")
                        current = _urljoin(current, location)
                        assert_public_url(current)
                        continue
                    response.raise_for_status()
                    assert_public_url(str(response.url))
                    chunks: list[bytes] = []
                    total = 0
                    for chunk in response.iter_bytes(65536):
                        total += len(chunk)
                        if total > limit:
                            raise AppError("Download exceeds size limit", code="too_large", status_code=413)
                        chunks.append(chunk)
                    return b"".join(chunks).decode("utf-8", errors="ignore")
            raise AppError("Too many redirects", code="fetch_failed")
    except AppError:
        raise
    except Exception as exc:
        raise AppError(f"Download failed: {exc}", code="fetch_failed") from exc


def _to_raw_url(url: str) -> str:
    """Convert GitHub blob URLs to raw URLs; pass through raw URLs."""
    match = re.match(r"https://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)", url)
    if match:
        owner, repo, ref, path = match.groups()
        return f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}"
    return url


def install_from_url(workspace: str, url: str) -> list[InstalledSkill]:
    url = url.strip()
    if re.match(r"https://github\.com/[^/]+/[^/]+/?$", url.rstrip("/")):
        parts = url.rstrip("/").split("/")
        return install_from_github(workspace, f"{parts[-2]}/{parts[-1]}")
    if url.lower().endswith(".zip"):
        return install_from_zip_url(workspace, url)
    raw = _to_raw_url(url)
    text = _fetch_text(raw)
    meta, _ = parse_skill_text(text)
    slug = slugify_skill(str(meta["name"]))
    return [write_skill(workspace, slug, text, origin="url", origin_url=url)]


def install_from_zip_url(workspace: str, url: str) -> list[InstalledSkill]:
    if not url.startswith(("https://", "http://")):
        raise AppError("Only http(s) URLs are supported", code="bad_url")
    from urllib.parse import urljoin as _urljoin

    from app.core.net import assert_public_url

    assert_public_url(url)
    try:
        current = url
        data = b""
        with httpx.Client(timeout=60, follow_redirects=False) as client:
            for _ in range(6):
                response = client.get(current, headers={"User-Agent": "BhatiAiAgent/2.0"})
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location", "")
                    if not location:
                        raise AppError("Redirect without location", code="fetch_failed")
                    current = _urljoin(current, location)
                    assert_public_url(current)
                    continue
                response.raise_for_status()
                assert_public_url(str(response.url))
                data = response.content
                break
            else:
                raise AppError("Too many redirects", code="fetch_failed")
    except AppError:
        raise
    except Exception as exc:
        raise AppError(f"Download failed: {exc}", code="fetch_failed") from exc
    if len(data) > ZIP_LIMIT_BYTES:
        raise AppError("Archive exceeds 50 MB", code="too_large", status_code=413)
    return _install_from_zip_bytes(workspace, data, origin="url", origin_url=url)


def _install_from_zip_bytes(workspace: str, data: bytes, origin: str, origin_url: str = "") -> list[InstalledSkill]:
    root = _skills_root(workspace)
    installed: list[InstalledSkill] = []
    with tempfile.TemporaryDirectory(prefix="bhati-skill-") as tmp:
        tmp_path = Path(tmp)
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                # Zip-bomb guard: cap uncompressed total + member count first.
                total_uncompressed = 0
                members = zf.infolist()
                if len(members) > 500:
                    raise AppError("Archive has too many files", code="too_large", status_code=413)
                for member in members:
                    total_uncompressed += member.file_size
                    if total_uncompressed > 100_000_000:
                        raise AppError("Archive uncompresses past 100 MB", code="too_large", status_code=413)
                for member in members:
                    target = (tmp_path / member.filename).resolve()
                    if tmp_path.resolve() not in target.parents and target != tmp_path.resolve():
                        continue  # zip-slip protection
                    zf.extract(member, tmp_path)
        except zipfile.BadZipFile as exc:
            raise AppError(f"Invalid archive: {exc}", code="bad_archive") from exc
        for skill_file in _find_skill_files(tmp_path):
            try:
                text = skill_file.read_text(encoding="utf-8", errors="ignore")
                meta, _ = parse_skill_text(text)
                slug = slugify_skill(str(meta["name"]))
                installed.append(write_skill(workspace, slug, text, origin=origin, origin_url=origin_url))
                # Copy supporting files (scripts/, references/, assets/).
                src_dir = skill_file.parent
                dest_dir = root / slug
                for extra in src_dir.rglob("*"):
                    if extra.is_file() and extra.name.lower() != "skill.md":
                        rel = extra.relative_to(src_dir)
                        dest = (dest_dir / rel).resolve()
                        if dest_dir.resolve() in dest.parents:
                            dest.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(extra, dest)
            except (AppError, OSError) as exc:
                log.warning("skipping %s from archive: %s", skill_file, exc)
    if not installed:
        raise AppError("No valid SKILL.md found in archive", code="bad_archive")
    return installed


def _find_skill_files(base: Path) -> list[Path]:
    found: list[Path] = []
    for path in base.rglob("*"):
        if path.is_file() and path.name.lower() == "skill.md" and len(found) < 50:
            try:
                if len(path.relative_to(base).parts) <= MAX_DEPTH + 1:
                    found.append(path)
            except ValueError:
                pass
    return sorted(found)


def parse_github_spec(spec: str) -> tuple[str, str, str, str]:
    """Parse `owner/repo[@ref][/subpath]` into components."""
    match = re.match(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)(?:@([^/]+))?(?:/(.+))?$", spec.strip())
    if not match:
        raise AppError(
            "Use owner/repo, owner/repo@branch, or owner/repo/path/to/skill", code="bad_spec"
        )
    owner, repo, ref, subpath = match.groups()
    return owner, repo, ref or "main", (subpath or "").strip("/")


def _github_api(path: str, params: dict[str, Any] | None = None) -> Any:
    try:
        with httpx.Client(timeout=30) as client:
            response = client.get(
                f"https://api.github.com{path}", headers=_github_headers(), params=params or {}
            )
            if response.status_code == 404:
                raise AppError("Not found on GitHub (missing, private, or renamed)", code="not_found", status_code=404)
            if response.status_code == 403 and "rate limit" in response.text.lower():
                raise AppError("GitHub API rate limit hit — add GITHUB_TOKEN and retry", code="rate_limited", status_code=429)
            response.raise_for_status()
            return response.json()
    except AppError:
        raise
    except Exception as exc:
        raise AppError(f"GitHub request failed: {exc}", code="fetch_failed") from exc


def browse_github_repo(spec: str) -> list[dict[str, Any]]:
    """List installable skills in any public GitHub repo (SKILL.md discovery)."""
    owner, repo, ref, subpath = parse_github_spec(spec)
    nodes = _github_tree_nodes(owner, repo, ref)
    out: list[dict[str, Any]] = []
    for node in nodes:
        path = str(node.get("path", ""))
        if node.get("type") != "blob" or not path.lower().endswith("skill.md"):
            continue
        if subpath and not (path == subpath or path.startswith(subpath.rstrip("/") + "/")):
            continue
        out.append({"path": path, "size": node.get("size", 0), "repo": f"{owner}/{repo}", "ref": ref})
        if len(out) >= 50:
            break
    # Enrich with frontmatter (best effort, cheap for small lists).
    for entry in out[:50]:
        try:
            raw = _fetch_text(
                f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{entry['path']}", limit=65536
            )
            meta, _ = parse_skill_text(raw)
            entry["name"] = str(meta.get("name"))
            entry["description"] = str(meta.get("description", ""))[:200]
        except AppError:
            entry["name"] = Path(entry["path"]).parent.name
            entry["description"] = ""
    return out


def _github_tree_nodes(owner: str, repo: str, ref: str) -> list[dict[str, Any]]:
    """Full recursive file listing for a repo ref (shared by browse/install)."""
    tree = _github_api(f"/repos/{owner}/{repo}/git/trees/{ref}", {"recursive": "1"})
    if not isinstance(tree, dict) or tree.get("truncated"):
        log.warning("github tree truncated for %s/%s@%s", owner, repo, ref)
    nodes = tree.get("tree") or []
    return [n for n in nodes[:5000] if isinstance(n, dict)]


SIBLING_MAX_FILES = 20
SIBLING_MAX_BYTES = 262_144


def _copy_skill_siblings(
    root: Path,
    slug: str,
    owner: str,
    repo: str,
    ref: str,
    skill_dir: str,
    nodes: list[dict[str, Any]],
) -> int:
    """Download supporting files (scripts/, references/, assets/) next to an
    installed SKILL.md so marketplace/GitHub skills work complete, not bare."""
    if not skill_dir:
        return 0
    dest_dir = root / slug
    copied = 0
    prefix = skill_dir.rstrip("/") + "/"
    for node in nodes:
        if copied >= SIBLING_MAX_FILES:
            break
        if node.get("type") != "blob":
            continue
        path = str(node.get("path", ""))
        if not path.startswith(prefix):
            continue
        rel = path[len(prefix):]
        if not rel or rel.lower() == "skill.md" or rel.count("/") > 2:
            continue
        if int(node.get("size") or 0) > SIBLING_MAX_BYTES:
            continue
        try:
            text = _fetch_text(
                f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{path}",
                limit=SIBLING_MAX_BYTES,
            )
            dest = (dest_dir / rel).resolve()
            if dest_dir.resolve() in dest.parents:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(text, encoding="utf-8")
                copied += 1
        except (AppError, OSError) as exc:
            log.warning("skipping sibling %s: %s", path, exc)
    return copied


def install_from_github(workspace: str, spec: str, only: list[str] | None = None) -> list[InstalledSkill]:
    owner, repo, ref, subpath = parse_github_spec(spec)
    entries = browse_github_repo(spec)
    if only:
        wanted = set(only)
        entries = [e for e in entries if e["path"] in wanted or e.get("name") in wanted]
    if not entries:
        raise AppError("No SKILL.md files found in that repo/path", code="not_found", status_code=404)
    root = _skills_root(workspace)
    nodes = _github_tree_nodes(owner, repo, ref)
    installed: list[InstalledSkill] = []
    for entry in entries[:20]:
        raw = f"https://raw.githubusercontent.com/{owner}/{repo}/{ref}/{entry['path']}"
        text = _fetch_text(raw)
        meta, _ = parse_skill_text(text)
        slug = slugify_skill(str(meta["name"]))
        installed.append(
            write_skill(workspace, slug, text, origin="github", origin_url=f"https://github.com/{owner}/{repo}/tree/{ref}")
        )
        skill_dir = entry["path"].rsplit("/", 1)[0] if "/" in entry["path"] else ""
        _copy_skill_siblings(root, slug, owner, repo, ref, skill_dir, nodes)
    _ = subpath
    return installed


# --------------------------------------------------------------- marketplace ---


@dataclass
class MarketplaceSkill:
    id: str
    name: str
    description: str
    source: str  # e.g. "Anthropic Official"
    raw_url: str
    repo_url: str
    license: str = ""


MARKETPLACE: list[MarketplaceSkill] = [
    MarketplaceSkill(
        id="anthropic-docx", name="docx",
        description="Create, edit and read .docx Word documents with tracked changes, tables and styling.",
        source="Anthropic Official", license="Source-available",
        raw_url="https://raw.githubusercontent.com/anthropics/skills/main/skills/docx/SKILL.md",
        repo_url="https://github.com/anthropics/skills/tree/main/skills/docx",
    ),
    MarketplaceSkill(
        id="anthropic-pdf", name="pdf",
        description="PDF ops in code: read, merge, split, rotate, watermark, forms, OCR on scanned pages.",
        source="Anthropic Official", license="Source-available",
        raw_url="https://raw.githubusercontent.com/anthropics/skills/main/skills/pdf/SKILL.md",
        repo_url="https://github.com/anthropics/skills/tree/main/skills/pdf",
    ),
    MarketplaceSkill(
        id="anthropic-pptx", name="pptx",
        description="Build and edit PowerPoint decks: slides, layouts, speaker notes, charts.",
        source="Anthropic Official", license="Source-available",
        raw_url="https://raw.githubusercontent.com/anthropics/skills/main/skills/pptx/SKILL.md",
        repo_url="https://github.com/anthropics/skills/tree/main/skills/pptx",
    ),
    MarketplaceSkill(
        id="anthropic-xlsx", name="xlsx",
        description="Excel and tabular files: pandas analysis, openpyxl formulas and formatting.",
        source="Anthropic Official", license="Source-available",
        raw_url="https://raw.githubusercontent.com/anthropics/skills/main/skills/xlsx/SKILL.md",
        repo_url="https://github.com/anthropics/skills/tree/main/skills/xlsx",
    ),
    MarketplaceSkill(
        id="anthropic-frontend-design", name="frontend-design",
        description="Production-grade frontend interfaces with strong visual design instincts.",
        source="Anthropic Official", license="Apache-2.0",
        raw_url="https://raw.githubusercontent.com/anthropics/skills/main/skills/frontend-design/SKILL.md",
        repo_url="https://github.com/anthropics/skills/tree/main/skills/frontend-design",
    ),
    MarketplaceSkill(
        id="anthropic-webapp-testing", name="webapp-testing",
        description="Test web apps end-to-end: flows, forms, edge cases and regressions.",
        source="Anthropic Official", license="Apache-2.0",
        raw_url="https://raw.githubusercontent.com/anthropics/skills/main/skills/webapp-testing/SKILL.md",
        repo_url="https://github.com/anthropics/skills/tree/main/skills/webapp-testing",
    ),
    MarketplaceSkill(
        id="anthropic-mcp-builder", name="mcp-builder",
        description="Build MCP servers: tools, resources, prompts and transports done right.",
        source="Anthropic Official", license="Apache-2.0",
        raw_url="https://raw.githubusercontent.com/anthropics/skills/main/skills/mcp-builder/SKILL.md",
        repo_url="https://github.com/anthropics/skills/tree/main/skills/mcp-builder",
    ),
    MarketplaceSkill(
        id="anthropic-skill-creator", name="skill-creator",
        description="Meta-skill: design, write and validate new Agent Skills correctly.",
        source="Anthropic Official", license="Apache-2.0",
        raw_url="https://raw.githubusercontent.com/anthropics/skills/main/skills/skill-creator/SKILL.md",
        repo_url="https://github.com/anthropics/skills/tree/main/skills/skill-creator",
    ),
]

_marketplace_cache: dict[str, Any] = {"at": 0.0, "items": []}


def marketplace_live(query: str = "") -> list[dict[str, Any]]:
    """Curated catalog merged with the live anthropics/skills repo listing."""
    items: list[dict[str, Any]] = [
        {
            "id": m.id, "name": m.name, "description": m.description, "source": m.source,
            "repo_url": m.repo_url, "raw_url": m.raw_url, "license": m.license, "live": False,
        }
        for m in MARKETPLACE
    ]
    known = {m.name for m in MARKETPLACE}
    now = time.time()
    live: list[dict[str, Any]] = []
    if now - _marketplace_cache["at"] < 3600 and _marketplace_cache["items"]:
        live = _marketplace_cache["items"]
    else:
        try:
            data = _github_api("/repos/anthropics/skills/contents/skills", {"ref": "main"})
            if isinstance(data, list):
                for node in data:
                    if node.get("type") == "dir" and node.get("name") not in known:
                        live.append({
                            "id": f"anthropic-{node['name']}", "name": node["name"],
                            "description": "Community example skill from anthropics/skills.",
                            "source": "Anthropic Examples", "repo_url": node.get("html_url", ""),
                            "license": "Apache-2.0", "live": True,
                            "raw_url": f"https://raw.githubusercontent.com/anthropics/skills/main/skills/{node['name']}/SKILL.md",
                        })
                _marketplace_cache.update({"at": now, "items": live})
        except AppError as exc:
            log.warning("marketplace live listing failed: %s", exc)
    items.extend(live)
    # Second source: mcpservers.org community library (kept separate via
    # source badge; failures here never affect the Anthropic catalog).
    try:
        items.extend(mso_listing())
    except Exception as exc:
        log.warning("mso marketplace merge failed: %s", exc)
    if query.strip():
        needle = query.strip().lower()
        items = [i for i in items if needle in i["name"].lower() or needle in i["description"].lower()]
    return items


def install_from_marketplace(workspace: str, skill_id: str) -> InstalledSkill:
    if skill_id.startswith("mso-"):
        return install_from_mso(workspace, skill_id)
    for item in marketplace_live():
        if item["id"] == skill_id:
            raw_url = item.get("raw_url") or ""
            if not raw_url:
                raise AppError("Marketplace entry has no downloadable file", code="bad_skill")
            text = _fetch_text(raw_url)
            meta, _ = parse_skill_text(text)
            slug = slugify_skill(str(meta["name"]))
            return write_skill(workspace, slug, text, origin="marketplace", origin_url=item.get("repo_url", ""))
    raise AppError(f"Unknown marketplace skill: {skill_id}", code="not_found", status_code=404)


# --------------------------------------------- mcpservers.org marketplace ---

MSO_BASE = "https://mcpservers.org"
MSO_TTL = 3600

_mso_cache: dict[str, Any] = {"at": 0.0, "items": []}

MSO_CARD_RE = re.compile(
    r'<a href="(/agent-skills/(?!author/|category/)([a-z0-9-]+)/([a-z0-9-]+))"[^>]*>(.*?)</a>',
    re.DOTALL,
)
MSO_TITLE_RE = re.compile(
    r'<div class="[^"]*font-semibold[^"]*">([^<]{1,120})</div>'
)
MSO_DESC_RE = re.compile(
    r'data-slot="card-description"[^>]*>([^<]{1,600})</div>'
)
MSO_TAG_RE = re.compile(
    r'<span class="rounded-md border[^"]*">([^<]{1,40})</span>'
)
MSO_GITHUB_RE = re.compile(
    r"https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/tree/([^/\"')\s]+)/([^\"')\s]+)"
)


def mso_listing(query: str = "") -> list[dict[str, Any]]:
    """Community skills from mcpservers.org/agent-skills (cached 1h).

    Failures never propagate — the Anthropic catalog must keep working even
    when this directory is unreachable.
    """
    now = time.time()
    items: list[dict[str, Any]] = []
    if now - _mso_cache["at"] < MSO_TTL and _mso_cache["items"]:
        items = _mso_cache["items"]
    else:
        try:
            html = _fetch_text(f"{MSO_BASE}/agent-skills")
        except AppError as exc:
            log.warning("mcpservers.org skills listing failed: %s", exc)
            return []
        seen: set[str] = set()
        for _href, author, slug, inner in MSO_CARD_RE.findall(html):
            key = f"{author}/{slug}"
            if key in seen:
                continue
            seen.add(key)
            title = MSO_TITLE_RE.search(inner)
            desc = MSO_DESC_RE.search(inner)
            tags = MSO_TAG_RE.findall(inner)[:6]
            name = title.group(1).strip() if title else slug.replace("-", " ")
            items.append(
                {
                    "id": f"mso-{author}-{slug}",
                    "name": slug,
                    "title": name,
                    "description": (desc.group(1).strip() if desc else ""),
                    "source": "mcpservers.org",
                    "author": author,
                    "tags": [t.strip() for t in tags],
                    "repo_url": f"{MSO_BASE}/agent-skills/{author}/{slug}",
                    "live": True,
                }
            )
            if len(items) >= 400:
                break
        _mso_cache.update({"at": now, "items": items})
    if query.strip():
        needle = query.strip().lower()
        items = [
            i
            for i in items
            if needle in i["name"].lower()
            or needle in i["description"].lower()
            or needle in i.get("title", "").lower()
        ]
    return items


def mso_github_spec(author: str, skill: str) -> str:
    """Resolve an mcpservers.org entry to owner/repo@ref/subpath via its page."""
    if not re.fullmatch(r"[a-z0-9-]+", author) or not re.fullmatch(r"[a-z0-9-]+", skill):
        raise AppError("Invalid marketplace entry", code="bad_skill")
    html = _fetch_text(f"{MSO_BASE}/agent-skills/{author}/{skill}")
    match = MSO_GITHUB_RE.search(html)
    if not match:
        raise AppError(
            "This entry has no GitHub source to install from", code="not_installable"
        )
    owner, repo, ref, subpath = match.groups()
    return f"{owner}/{repo}@{ref}/{subpath.rstrip('/')}"


def install_from_mso(workspace: str, skill_id: str) -> InstalledSkill:
    """Install one mcpservers.org skill through its GitHub source repo."""
    target = next((i for i in mso_listing() if i["id"] == skill_id), None)
    if target is None:
        raise AppError(f"Unknown marketplace skill: {skill_id}", code="not_found", status_code=404)
    spec = mso_github_spec(target["author"], target["name"])
    installed = install_from_github(workspace, spec)
    if not installed:
        raise AppError("Install produced no skills", code="internal")
    return installed[0]


# ------------------------------------------------------------------ manage ---


def set_skill_enabled(workspace: str, name: str, enabled: bool) -> InstalledSkill:
    root = _skills_root(workspace)
    names = {s.name for s in discover_skills(workspace)}
    if name not in names:
        raise AppError(f"Skill not found: {name}", code="not_found", status_code=404)
    state = _load_state(root)
    disabled = set(state.get("disabled", []))
    if enabled:
        disabled.discard(name)
    else:
        disabled.add(name)
    state["disabled"] = sorted(disabled)
    _save_state(root, state)
    for skill in discover_skills(workspace):
        if skill.name == name:
            return skill
    raise AppError("Skill not found after update", code="internal")


def delete_skill(workspace: str, name: str) -> None:
    root = _skills_root(workspace)
    target_dir = (root / name).resolve()
    removed = False
    if target_dir != root.resolve() and root.resolve() in target_dir.parents and target_dir.is_dir():
        shutil.rmtree(target_dir, ignore_errors=True)
        removed = True
    flat = (root / f"{name}.md").resolve()
    if not removed and flat.is_file() and root.resolve() in flat.parents:
        flat.unlink(missing_ok=True)
        removed = True
    if not removed:
        raise AppError(f"Skill not found: {name}", code="not_found", status_code=404)
    state = _load_state(root)
    disabled = set(state.get("disabled", []))
    disabled.discard(name)
    state["disabled"] = sorted(disabled)
    _save_state(root, state)
