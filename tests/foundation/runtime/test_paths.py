"""Unit tests for foundation.runtime.paths."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest

from edgar_sec.foundation.runtime.paths import (
    CHECKPOINTS_DIR,
    DOCUMENTS_DATASET,
    FIXTURE_MANIFEST_NAME,
    FIXTURES_DIR,
    PACKAGE_ROOT,
    PAYLOAD_DB_NAME,
    REVIEW_RUNS_DIR,
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
    monkeypatch.setenv("ARTIFACTS_ROOT", str(override))
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
    assert paths.fixtures_root == paths.artifacts_root / FIXTURES_DIR


def test_run_layout_hangs_off_the_transient_root(paths: ProjectPaths) -> None:
    run = paths.run_dir("2024-01-01")
    assert run == paths.document_transient_root / RUNS_DIR / "2024-01-01"
    assert paths.run_checkpoints_dir("2024-01-01") == run / CHECKPOINTS_DIR
    assert paths.run_chunks_dir("2024-01-01") == run / "chunks"


def test_review_runs_are_durable_and_not_under_the_transient_root(
    paths: ProjectPaths,
) -> None:
    """A review run is a deliverable compared across runs, not pipeline staging."""
    review = paths.review_run_dir("review-1")
    assert review == paths.review_runs_root / "review-1"
    assert paths.review_runs_root == (
        paths.artifacts_root / DOCUMENTS_DATASET / REVIEW_RUNS_DIR
    )
    assert paths.document_transient_root not in review.parents


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
    assert paths.fixture_db_path("fix-1").name == "fixture.sqlite"
    assert paths.fixture_manifest_path("fix-1").name == "fixture.manifest.json"


def test_fixtures_do_not_live_under_a_run(paths: ProjectPaths) -> None:
    """A fixture must outlive any single run, so the trees stay disjoint."""
    assert paths.fixtures_root not in paths.run_dir("2024-01-01").parents
    assert paths.documents_root not in paths.run_dir("2024-01-01").parents


def test_broker_socket_under_runtime_root(paths: ProjectPaths) -> None:
    assert paths.broker_socket_path.parent == paths.runtime_root


def test_project_paths_offers_no_second_cache_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exactly one authority may answer "where is the cache?".

    `ProjectPaths` once carried its own cache root, under a different
    environment variable and defaulting to a different directory than the
    registered `cache.root` spec. Nothing read it, so a caller that reached for
    the wrong one would open an empty store beside the populated one and
    silently forfeit every cached response. The spec is the only answer.
    """
    monkeypatch.setenv("EDGAR_CACHE_DIR", str(Path("/tmp/should-be-ignored")))
    paths = resolve_paths(repo_root=Path.cwd())
    assert not hasattr(paths, "cache_root")
    assert "cache_root" not in {field.name for field in fields(ProjectPaths)}


def test_the_cache_root_has_exactly_one_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """`EDGAR_CACHE_DIR` is gone; `CACHE_ROOT` is the registered override."""
    from edgar_sec.foundation.runtime.settings import resolve_settings

    monkeypatch.setenv("EDGAR_CACHE_DIR", "/tmp/ignored-cache")
    assert str(resolve_settings()["cache.root"]) != "/tmp/ignored-cache"

    monkeypatch.setenv("CACHE_ROOT", "/tmp/registered-cache")
    assert str(resolve_settings()["cache.root"]) == "/tmp/registered-cache"


def test_the_registry_and_the_resolver_agree_on_the_artifacts_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One question, one answer.

    The resolver used to read a private `EDGAR_ARTIFACTS_DIR` while the registry
    advertised `ARTIFACTS_ROOT`, so each ignored the other: setting one left the
    other reporting the default. Anyone who set the documented variable got a
    silent no-op from the code that actually built the paths.

    "Agree" means the resolver produces exactly the registered value, anchored to
    the project root when the registered value is relative and taken as given
    when it is absolute.
    """
    from edgar_sec.foundation.runtime.settings import resolve_settings

    for value in (".artifacts", "custom-root", str(tmp_path / "absolute")):
        monkeypatch.setenv("ARTIFACTS_ROOT", value)
        registered = Path(str(resolve_settings()["artifacts.root"]))
        expected = registered if registered.is_absolute() else tmp_path / registered
        assert resolve_paths(repo_root=tmp_path).artifacts_root == expected.resolve()


def test_a_relative_artifacts_root_is_anchored_to_the_project_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default must land beside the package, not in the process CWD."""
    monkeypatch.setenv("ARTIFACTS_ROOT", ".artifacts")
    assert resolve_paths(repo_root=tmp_path).artifacts_root == tmp_path / ".artifacts"


def test_an_absolute_artifacts_root_is_taken_as_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "side-by-side"
    monkeypatch.setenv("ARTIFACTS_ROOT", str(target))
    assert resolve_paths(repo_root=Path("/somewhere/else")).artifacts_root == target


def test_edgar_artifacts_dir_is_no_longer_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The retired variable must be inert, not a silent second answer."""
    monkeypatch.setenv("ARTIFACTS_ROOT", ".artifacts")
    monkeypatch.setenv("EDGAR_ARTIFACTS_DIR", str(tmp_path / "ignored"))
    assert resolve_paths(repo_root=tmp_path).artifacts_root == tmp_path / ".artifacts"
