"""Unit tests for foundation.runtime.paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.runtime.paths import resolve_paths


def test_resolve_paths_derives_artifacts_root(tmp_path: Path) -> None:
    paths = resolve_paths(repo_root=tmp_path)
    assert paths.repo_root == tmp_path
    assert paths.artifacts_root == tmp_path / ".artifacts"


def test_ensure_directories_is_idempotent(tmp_path: Path) -> None:
    paths = resolve_paths(repo_root=tmp_path)
    paths.ensure_directories()
    assert paths.artifacts_root.is_dir()
    paths.ensure_directories()
    assert paths.artifacts_root.is_dir()


def test_explicit_artifacts_root_overrides_repo_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override = tmp_path / "custom"
    monkeypatch.setenv("EDGAR_ARTIFACTS_DIR", str(override))
    paths = resolve_paths(repo_root=tmp_path)
    assert paths.artifacts_root == override.resolve()
