from pathlib import Path

import pytest

from edgar_sec.foundation.runtime.paths import ProjectPaths
from edgar_sec.infra.storage.cohort.paths import (
    CATALOG_DB_NAME,
    CohortPaths,
    resolve_cohort_paths,
)


def test_layout_and_relative_round_trip(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    assert paths.cohorts_root == tmp_path / "cohorts"
    assert paths.catalog_file == tmp_path / "cohorts" / CATALOG_DB_NAME
    assert paths.cohort_dataset_file("c-0123456789abcdef") == (
        tmp_path / "cohorts" / "c-0123456789abcdef" / "ciks.parquet"
    )
    dataset = paths.cohort_dataset_file("c-0123456789abcdef")
    assert paths.relative_path(dataset) == "c-0123456789abcdef/ciks.parquet"
    assert paths.resolve_relative_path("c-0123456789abcdef/ciks.parquet") == dataset


@pytest.mark.parametrize("cohort_id", ["../escape", "abc/def", "abc\\def", "..hidden"])
def test_cohort_dir_rejects_unsafe_identifiers(tmp_path: Path, cohort_id: str) -> None:
    with pytest.raises(ValueError):
        CohortPaths(tmp_path).cohort_dir(cohort_id)


@pytest.mark.parametrize(
    "relative_path", ["../outside", "/absolute/file", "a/../../b", "a\\b", "C:/file"]
)
def test_relative_resolver_rejects_traversal(
    tmp_path: Path, relative_path: str
) -> None:
    with pytest.raises(ValueError):
        CohortPaths(tmp_path).resolve_relative_path(relative_path)


def test_paths_reject_resolved_symlink_escape(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    paths.cohorts_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (paths.cohorts_root / "linked").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        paths.resolve_relative_path("linked/data.parquet")
    with pytest.raises(ValueError):
        paths.relative_path(outside / "data.parquet")


def test_cohort_directory_rejects_sibling_symlink(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    paths.cohorts_root.mkdir()
    (paths.cohorts_root / "other-cohort").mkdir()
    (paths.cohorts_root / "c-0123456789abcdef").symlink_to(
        paths.cohorts_root / "other-cohort", target_is_directory=True
    )
    with pytest.raises(ValueError):
        paths.cohort_dir("c-0123456789abcdef")


def test_staging_publication_renames_within_root(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    stage = paths.create_staging_dir("c-0123456789abcdef")
    staged_file = stage / "ciks.parquet"
    staged_file.write_bytes(b"cohort")

    published = paths.publish_staging_dir("c-0123456789abcdef", stage)

    assert published == paths.cohort_dir("c-0123456789abcdef")
    assert (published / "ciks.parquet").read_bytes() == b"cohort"
    assert not stage.exists()


def test_staging_publication_refuses_unrelated_paths(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    paths.cohorts_root.mkdir()
    outside = tmp_path / ".stage-c-0123456789abcdef-outsider"
    outside.mkdir()
    with pytest.raises(ValueError):
        paths.publish_staging_dir("c-0123456789abcdef", outside)


def test_staging_publication_does_not_replace_existing_dataset(tmp_path: Path) -> None:
    paths = CohortPaths(tmp_path)
    existing = paths.cohort_dir("c-0123456789abcdef")
    existing.mkdir(parents=True)
    stage = paths.create_staging_dir("c-0123456789abcdef")
    with pytest.raises(FileExistsError):
        paths.publish_staging_dir("c-0123456789abcdef", stage)


def test_resolver_uses_project_path_artifacts_root(tmp_path: Path) -> None:
    project_paths = ProjectPaths(
        tmp_path, tmp_path / "configured", tmp_path / "uploads"
    )
    assert resolve_cohort_paths(project_paths=project_paths).artifacts_root == (
        tmp_path / "configured"
    )
