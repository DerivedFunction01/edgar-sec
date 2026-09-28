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


def test_running_from_inside_the_package_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CWD is the project root, so running from the package forks the tree.

    Without this, `cd edgar_sec && python ../run.py filing-catalog status`
    reports an empty catalog from a parallel `edgar_sec/.artifacts/` instead of
    failing, and a full-corpus run would publish real work nobody reads.
    """
    from edgar_sec.foundation.runtime.paths import PACKAGE_ROOT, ProjectRootError

    monkeypatch.chdir(PACKAGE_ROOT)
    with pytest.raises(ProjectRootError, match="inside the edgar_sec package"):
        resolve_paths()


def test_running_from_a_subdirectory_of_the_package_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from edgar_sec.foundation.runtime.paths import PACKAGE_ROOT, ProjectRootError

    monkeypatch.chdir(PACKAGE_ROOT / "engine" / "selection")
    with pytest.raises(ProjectRootError, match="inside the edgar_sec package"):
        resolve_paths()


def test_an_explicit_repo_root_is_accepted_from_anywhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Naming the root is how a caller answers the question, so it is allowed."""
    from edgar_sec.foundation.runtime.paths import PACKAGE_ROOT

    monkeypatch.chdir(PACKAGE_ROOT)
    assert resolve_paths(repo_root=tmp_path).repo_root == tmp_path


def test_the_project_root_itself_is_not_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from edgar_sec.foundation.runtime.paths import PACKAGE_ROOT

    monkeypatch.chdir(PACKAGE_ROOT.parent)
    assert resolve_paths().artifacts_root == PACKAGE_ROOT.parent / ".artifacts"
