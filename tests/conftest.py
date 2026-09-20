"""Shared fixtures."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

collect_ignore_glob = ["fixtures/*"]

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def make_repo(tmp_path):
    """Create a temp repo from a {relative_path: content} mapping."""

    def _make(files: dict[str, str] | None = None) -> Path:
        repo = tmp_path / "repo"
        repo.mkdir(exist_ok=True)
        for rel, content in (files or {}).items():
            path = repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        return repo

    return _make


@pytest.fixture
def fixture_repo(tmp_path):
    """Copy a fixture (repo/ + its AGENTS.md) into a temp dir; returns the repo path."""

    def _copy(name: str) -> Path:
        dest = tmp_path / f"{name}-repo"
        shutil.copytree(FIXTURES / name / "repo", dest)
        shutil.copy(FIXTURES / name / "AGENTS.md", dest / "AGENTS.md")
        return dest

    return _copy
