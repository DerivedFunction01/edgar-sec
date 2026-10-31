"""Unit tests for review paths and filenames."""

from pathlib import Path

import pytest

from edgar_sec.infra.storage.review.paths import (
    ReviewPaths,
    is_diff_run_dir,
    new_diff_dir,
    new_review_run_dir,
    new_review_run_id,
    review_runs_root,
)


def test_review_runs_root_joins_dataset_and_review_dir(tmp_path: Path) -> None:
    root = review_runs_root(tmp_path, "inventory")
    assert root == tmp_path / "inventory" / "review-runs"

    with pytest.raises(ValueError):
        review_runs_root(tmp_path, "../outside")


def test_review_paths_reject_escaping_case_ids(tmp_path: Path) -> None:
    paths = ReviewPaths(tmp_path / "run-1")

    with pytest.raises(ValueError):
        paths.case_dir("../outside")
    with pytest.raises(ValueError):
        paths.patch_file("../outside")


def test_review_paths_resolves_standard_subpaths(tmp_path: Path) -> None:
    paths = ReviewPaths(tmp_path / "run-1")
    assert paths.cases_dir == tmp_path / "run-1" / "cases"
    assert paths.case_dir("case-a") == tmp_path / "run-1" / "cases" / "case-a"
    assert paths.summary_file.name == "summary.txt"
    assert paths.diff_manifest_file.name == "diff_manifest.json"
    assert paths.patches_dir == tmp_path / "run-1" / "patches"
    assert paths.patch_file("case-a").name == "case-a.patch"


def test_new_review_run_id_is_non_empty_and_alphanumeric() -> None:
    run_id = new_review_run_id()
    assert len(run_id) >= 14
    assert run_id.replace("_", "").isalnum()


def test_run_and_diff_directories_and_predicates(tmp_path: Path) -> None:
    run_dir = new_review_run_dir(tmp_path)
    assert run_dir.parent == tmp_path
    assert not is_diff_run_dir(run_dir)

    diff_dir = new_diff_dir(tmp_path)
    assert diff_dir.parent == tmp_path
    assert is_diff_run_dir(diff_dir)
