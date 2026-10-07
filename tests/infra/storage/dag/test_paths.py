"""Tests for DAGPaths filesystem layout and path resolution."""

from pathlib import Path

import pytest

from edgar_sec.infra.storage.dag.paths import (
    DAGPaths,
    PUBLICATION_LOCK_FILE,
    STAGING_PREFIX,
)


def test_catalog_file_resolves_to_sqlite(tmp_path: Path) -> None:
    paths = DAGPaths(tmp_path)
    expected = tmp_path / "catalog.sqlite"
    assert paths.catalog_file == expected


def test_branches_root(tmp_path: Path) -> None:
    paths = DAGPaths(tmp_path)
    assert paths.branches_root == tmp_path / "branches"


def test_branch_dir(tmp_path: Path) -> None:
    paths = DAGPaths(tmp_path)
    assert paths.branch_dir("main") == tmp_path / "branches" / "main"


def test_tags_root(tmp_path: Path) -> None:
    paths = DAGPaths(tmp_path)
    assert paths.tags_root == tmp_path / "tags"


def test_snapshot_dir(tmp_path: Path) -> None:
    paths = DAGPaths(tmp_path)
    assert paths.snapshot_dir("c0") == tmp_path / "c0"


def test_relation_dir(tmp_path: Path) -> None:
    paths = DAGPaths(tmp_path)
    assert paths.relation_dir("c0", "accessions") == tmp_path / "c0" / "accessions"


def test_part_file(tmp_path: Path) -> None:
    paths = DAGPaths(tmp_path)
    expected = tmp_path / "c0" / "accessions" / "part-00000.parquet"
    assert paths.part_file("c0", "accessions", 0) == expected


def test_part_file_index_format(tmp_path: Path) -> None:
    paths = DAGPaths(tmp_path)
    expected = tmp_path / "c0" / "accessions" / "part-00042.parquet"
    assert paths.part_file("c0", "accessions", 42) == expected


def test_staging_dir(tmp_path: Path) -> None:
    paths = DAGPaths(tmp_path)
    assert paths.staging_dir("c0") == tmp_path / f"{STAGING_PREFIX}c0"


def test_is_staging_name_true() -> None:
    assert DAGPaths.is_staging_name(".stage-c0") is True


def test_is_staging_name_false() -> None:
    assert DAGPaths.is_staging_name("c0") is False
    assert DAGPaths.is_staging_name(".other-c0") is False


def test_list_staging_dirs_empty_when_no_root(tmp_path: Path) -> None:
    paths = DAGPaths(tmp_path / "nonexistent")
    assert paths.list_staging_dirs() == []


def test_list_staging_dirs_filters_correctly(tmp_path: Path) -> None:
    (tmp_path / ".stage-c0").mkdir()
    (tmp_path / ".stage-c1").mkdir()
    (tmp_path / "c0").mkdir()
    (tmp_path / "branches").mkdir()
    paths = DAGPaths(tmp_path)
    staging = paths.list_staging_dirs()
    assert [d.name for d in staging] == [".stage-c0", ".stage-c1"]


def test_list_staging_dirs_returns_sorted(tmp_path: Path) -> None:
    (tmp_path / ".stage-c2").mkdir()
    (tmp_path / ".stage-c0").mkdir()
    (tmp_path / ".stage-c1").mkdir()
    paths = DAGPaths(tmp_path)
    staging = paths.list_staging_dirs()
    assert [d.name for d in staging] == [".stage-c0", ".stage-c1", ".stage-c2"]


def test_publication_lock_path(tmp_path: Path) -> None:
    paths = DAGPaths(tmp_path)
    assert paths.publication_lock_path == tmp_path / PUBLICATION_LOCK_FILE


def test_publication_lock_file_constant() -> None:
    assert PUBLICATION_LOCK_FILE == ".publication.lock"
