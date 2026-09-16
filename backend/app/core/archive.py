"""Workspace ZIP archive builder.

Streams workspace files (or a sub-path) into a ZIP file on disk, skipping
dependency/build artefacts and enforcing file-count + byte caps so a single
download can never exhaust host disk or memory.
"""

from __future__ import annotations

import os
import re
import tempfile
import zipfile
from pathlib import Path

from app.core.errors import AppError

IGNORE_DIRS = frozenset(
    {
        "node_modules",
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        ".env",
        "dist",
        "build",
        ".next",
        ".nuxt",
        ".cache",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".idea",
        ".vscode",
    }
)

IGNORE_SUFFIXES = (".pyc", ".pyo", ".tsbuildinfo", ".log")

MAX_FILES = 20_000
MAX_BYTES = 500 * 1024 * 1024


def slugify_filename(name: str, fallback: str = "workspace") -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", (name or "").strip()).strip("-")
    return slug or fallback


def resolve_inside(root: Path, subpath: str = "") -> Path:
    """Resolve `subpath` strictly inside `root`; raises AppError on escape."""
    root = root.resolve()
    target = (root / (subpath or "")).resolve()
    if target != root and root not in target.parents:
        raise AppError("Path escapes workspace", code="path_escape")
    return target


def build_workspace_zip(root: Path, subpath: str = "") -> Path:
    """Zip `root/subpath` to a temp `.zip` file and return its path.

    Synchronous + CPU/IO bound — callers must run it via `asyncio.to_thread`.
    Raises AppError when caps are exceeded.
    """
    root = root.resolve()
    target = resolve_inside(root, subpath)
    if not target.exists():
        raise AppError(f"Path not found: {subpath or '.'}", code="not_found", status_code=404)

    fd, tmp_name = tempfile.mkstemp(prefix="bhati-archive-", suffix=".zip")
    os.close(fd)
    tmp = Path(tmp_name)

    prefix = slugify_filename(target.name) if target.is_file() else ""
    total_bytes = 0
    file_count = 0

    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            if target.is_file():
                if target.stat().st_size > MAX_BYTES:
                    raise AppError("File exceeds 500 MB download limit", code="too_large", status_code=413)
                zf.write(target, prefix or target.name)
                return tmp

            base = target
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames[:] = sorted(d for d in dirnames if d not in IGNORE_DIRS)
                for filename in sorted(filenames):
                    if filename.endswith(IGNORE_SUFFIXES):
                        continue
                    full = Path(dirpath) / filename
                    try:
                        size = full.stat().st_size
                    except OSError:
                        continue
                    if file_count + 1 > MAX_FILES:
                        raise AppError(
                            "Workspace exceeds 20,000 files — download a subfolder instead",
                            code="too_large",
                            status_code=413,
                        )
                    if total_bytes + size > MAX_BYTES:
                        raise AppError(
                            "Workspace exceeds 500 MB — download a subfolder instead",
                            code="too_large",
                            status_code=413,
                        )
                    arcname = str(full.relative_to(base))
                    zf.write(full, arcname)
                    total_bytes += size
                    file_count += 1
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return tmp
