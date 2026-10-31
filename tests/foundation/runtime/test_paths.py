"""Unit tests for foundation.runtime.paths."""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest

from edgar_sec.foundation.runtime.paths import (
    PACKAGE_ROOT,
    ProjectPaths,
    ProjectRootError,
    dataset_root,
    resolve_paths,
    snapshots_root,
    transient_dataset_root,
)


def test_resolve_paths_derives_artifacts_root(tmp_path: Path) -> None:
    paths = resolve_paths(repo_root=tmp_path)
    assert paths.repo_root == tmp_path
    assert paths.artifacts_root == tmp_path / ".artifacts"
    assert paths.runtime_root == tmp_path / ".artifacts" / "runtime"


def test_dataset_roots_share_validated_layout(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "artifacts"

    assert dataset_root(artifacts_root, "document_inventory") == (
        artifacts_root / "document_inventory"
    )
    assert transient_dataset_root(artifacts_root, "document_inventory") == (
        artifacts_root / "transient" / "document_inventory"
    )
    assert snapshots_root(artifacts_root, "document_inventory") == (
        artifacts_root / "document_inventory" / "snapshots"
    )


@pytest.mark.parametrize("dataset", ["", "..", "../outside", "a/b"])
def test_dataset_root_rejects_unsafe_components(tmp_path: Path, dataset: str) -> None:
    with pytest.raises(ValueError):
        dataset_root(tmp_path, dataset)


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
    """The CWD is the project root, so running from the package forks the tree into
    a parallel ``edgar_sec/.artifacts/`` that reports an empty catalog.
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


def test_project_paths_offers_no_second_cache_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exactly one authority may answer "where is the cache?": a second root opens an
    empty store beside the populated one.
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
    """A documented variable the path builder ignores would be a silent no-op;
    a registered relative value anchors to the project root, absolute is as given.
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
