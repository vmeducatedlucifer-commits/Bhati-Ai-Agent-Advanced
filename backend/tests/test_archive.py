"""Workspace ZIP archive builder: contents, ignores, caps, path safety."""

from __future__ import annotations

import zipfile

import pytest

from app.core.archive import (
    build_workspace_zip,
    resolve_inside,
    slugify_filename,
)
from app.core.errors import AppError


def _write(root, relpath: str, content: str = "x") -> None:
    target = root / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def test_archive_contains_files_with_relative_paths(tmp_path):
    _write(tmp_path, "src/app.py", "print('hi')")
    _write(tmp_path, "README.md", "# docs")

    tmp_zip = build_workspace_zip(tmp_path, "")
    try:
        with zipfile.ZipFile(tmp_zip) as zf:
            names = sorted(zf.namelist())
        assert names == ["README.md", "src/app.py"]
    finally:
        tmp_zip.unlink(missing_ok=True)


def test_archive_skips_dependency_and_build_dirs(tmp_path):
    _write(tmp_path, "src/app.py", "print('hi')")
    _write(tmp_path, "node_modules/dep/index.js", "junk")
    _write(tmp_path, ".git/HEAD", "ref")
    _write(tmp_path, "dist/bundle.js", "junk")
    _write(tmp_path, "__pycache__/app.pyc", "junk")

    tmp_zip = build_workspace_zip(tmp_path, "")
    try:
        with zipfile.ZipFile(tmp_zip) as zf:
            names = zf.namelist()
        assert names == ["src/app.py"]
    finally:
        tmp_zip.unlink(missing_ok=True)


def test_archive_subfolder_only(tmp_path):
    _write(tmp_path, "a/one.txt", "1")
    _write(tmp_path, "b/two.txt", "2")

    tmp_zip = build_workspace_zip(tmp_path, "a")
    try:
        with zipfile.ZipFile(tmp_zip) as zf:
            names = zf.namelist()
        assert names == ["one.txt"]
    finally:
        tmp_zip.unlink(missing_ok=True)


def test_archive_single_file(tmp_path):
    _write(tmp_path, "notes/todo.txt", "buy milk")

    tmp_zip = build_workspace_zip(tmp_path, "notes/todo.txt")
    try:
        with zipfile.ZipFile(tmp_zip) as zf:
            assert zf.read("todo.txt") == b"buy milk"
    finally:
        tmp_zip.unlink(missing_ok=True)


def test_archive_rejects_path_escape(tmp_path):
    with pytest.raises(AppError):
        resolve_inside(tmp_path, "../outside")
    with pytest.raises(AppError):
        build_workspace_zip(tmp_path, "../../etc")


def test_archive_missing_path_is_404(tmp_path):
    with pytest.raises(AppError):
        build_workspace_zip(tmp_path, "nope/missing")


def test_slugify_filename():
    assert slugify_filename("My Cool Project!") == "My-Cool-Project"
    assert slugify_filename("") == "workspace"
    assert slugify_filename("   ") == "workspace"
