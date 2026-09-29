"""Unit tests for foundation.runtime.paths."""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.runtime.paths import (
    CHECKPOINTS_DIR,
    DOCUMENTS_DATASET,
    FIXTURE_MANIFEST_NAME,
    FIXTURES_DIR,
    PACKAGE_ROOT,
    PAYLOAD_DB_NAME,
    RUNS_DIR,
    SNAPSHOTS_DIR,
    TRANSIENT_DIR,
    ProjectPaths,
    ProjectRootError,
    resolve_paths,
)


def test_resolve_paths_derives_artifacts_root(tmp_path: Path) -> None:
    paths = resolve_paths(repo_root=tmp_path)
    assert paths.repo_root == tmp_path
    assert paths.artifacts_root == tmp_path / ".artifacts"


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

    monkeypatch.chdir(PACKAGE_ROOT)
    with pytest.raises(ProjectRootError, match="inside the edgar_sec package"):
        resolve_paths()


def test_running_from_a_subdirectory_of_the_package_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    monkeypatch.chdir(PACKAGE_ROOT / "engine" / "selection")
    with pytest.raises(ProjectRootError, match="inside the edgar_sec package"):
        resolve_paths()


def test_an_explicit_repo_root_is_accepted_from_anywhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Naming the root is how a caller answers the question, so it is allowed."""

    monkeypatch.chdir(PACKAGE_ROOT)
    assert resolve_paths(repo_root=tmp_path).repo_root == tmp_path


def test_the_project_root_itself_is_not_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    monkeypatch.chdir(PACKAGE_ROOT.parent)
    assert resolve_paths().artifacts_root == PACKAGE_ROOT.parent / ".artifacts"


@pytest.fixture
def paths(tmp_path: Path) -> ProjectPaths:
    return ProjectPaths(
        repo_root=tmp_path,
        artifacts_root=tmp_path / ".artifacts",
        cache_root=tmp_path / "cache",
        uploads_root=tmp_path / "uploads",
    )


def test_document_roots_are_segregated(paths: ProjectPaths) -> None:
    assert (
        paths.documents_root == paths.artifacts_root / DOCUMENTS_DATASET / SNAPSHOTS_DIR
    )
    assert (
        paths.document_transient_root
        == paths.artifacts_root / TRANSIENT_DIR / DOCUMENTS_DATASET
    )
    assert (
        paths.fixtures_root == paths.artifacts_root / DOCUMENTS_DATASET / FIXTURES_DIR
    )


def test_run_layout_hangs_off_the_transient_root(paths: ProjectPaths) -> None:
    run = paths.run_dir("2024-01-01")
    assert run == paths.document_transient_root / RUNS_DIR / "2024-01-01"
    assert paths.run_checkpoints_dir("2024-01-01") == run / CHECKPOINTS_DIR
    assert paths.run_chunks_dir("2024-01-01") == run / "chunks"
    assert paths.review_dir("2024-01-01") == run / "review"


def test_snapshot_dir(paths: ProjectPaths) -> None:
    assert paths.snapshot_dir("snap-7") == paths.documents_root / "snap-7"


def test_fixture_paths(paths: ProjectPaths) -> None:
    assert paths.fixture_dir("fix-1") == paths.fixtures_root / "fix-1"
    assert (
        paths.fixture_db_path("fix-1")
        == paths.fixtures_root / "fix-1" / PAYLOAD_DB_NAME
    )
    assert (
        paths.fixture_manifest_path("fix-1")
        == paths.fixtures_root / "fix-1" / FIXTURE_MANIFEST_NAME
    )


def test_fixtures_do_not_live_under_a_run(paths: ProjectPaths) -> None:
    """A fixture must outlive any single run, so the trees stay disjoint."""
    assert paths.fixtures_root not in paths.run_dir("2024-01-01").parents
    assert paths.documents_root not in paths.run_dir("2024-01-01").parents


def test_broker_socket_under_runtime_root(paths: ProjectPaths) -> None:
    assert paths.broker_socket_path.parent == paths.runtime_root
