from pathlib import Path

import pytest

from edgar_sec.foundation.runtime.paths import RUN_LOCK_FILE, RUN_MANIFEST_FILE
from edgar_sec.infra.storage.review.paths import REVIEW_RUNS_DIR
from edgar_sec.pipelines.document_acquisition.paths import (
    DATASET,
    RUN_CANCELLED_FILE,
    RUN_STAGING_DIR,
    RUN_STATE_FILE,
    WORK_ORDER_DIR,
    resolve_acquisition_paths,
)


def test_roots_and_run_paths_resolve_from_project_roots(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "configured-artifacts"
    paths = resolve_acquisition_paths(tmp_path, artifacts_root)
    run_id = "run-1"
    run_root = artifacts_root / "transient" / DATASET / run_id

    assert paths.project.repo_root == tmp_path
    assert paths.artifacts_root == artifacts_root
    assert paths.transient_root == artifacts_root / "transient"
    assert paths.runtime_root == artifacts_root / "runtime"
    assert paths.runs_root == artifacts_root / "transient" / DATASET
    assert paths.target_plan_dir("plan-1") == (
        artifacts_root / "document_planning" / "plans" / "plan-1"
    )
    assert paths.fixtures_root == artifacts_root / DATASET / "fixtures"
    assert paths.fixture_root("fixture-1") == paths.fixtures_root / "fixture-1"
    assert paths.fixture_manifest_path("fixture-1") == (
        paths.fixtures_root / "fixture-1" / "manifest.json"
    )
    assert paths.fixture_database_path("fixture-1") == (
        paths.fixtures_root / "fixture-1" / "fixture.sqlite"
    )
    assert paths.review_runs_root == artifacts_root / DATASET / REVIEW_RUNS_DIR
    review = paths.review_paths("review-1")
    assert review.root == artifacts_root / DATASET / REVIEW_RUNS_DIR / "review-1"
    assert review.manifest_path == review.root / "manifest.jsonl"
    assert review.case_dir("target-1") == review.root / "cases" / "target-1"
    assert paths.snapshots_root == artifacts_root / DATASET / "snapshots"
    assert paths.snapshot_root("snapshot-1") == paths.snapshots_root / "snapshot-1"
    assert paths.run_dir(run_id) == run_root
    assert paths.run_manifest_path(run_id) == run_root / RUN_MANIFEST_FILE
    assert paths.work_order_root(run_id) == run_root / WORK_ORDER_DIR
    assert paths.run_state_path(run_id) == run_root / RUN_STATE_FILE
    assert paths.run_lock_path(run_id) == run_root / RUN_LOCK_FILE
    assert paths.run_cancelled_path(run_id) == run_root / RUN_CANCELLED_FILE
    assert paths.run_staging_root(run_id) == run_root / RUN_STAGING_DIR


@pytest.mark.parametrize(
    "bad_id", ["", ".", "..", "../escape", "a/b", "a\\b", "a b", "a\nb"]
)
def test_run_ids_must_be_safe_path_components(tmp_path: Path, bad_id: str) -> None:
    paths = resolve_acquisition_paths(tmp_path, tmp_path / "artifacts")

    with pytest.raises(ValueError):
        paths.run_dir(bad_id)


@pytest.mark.parametrize("bad_id", ["", ".", "..", "../escape", "a/b", "a\\b"])
@pytest.mark.parametrize("method", ["fixture_root", "review_paths", "snapshot_root"])
def test_retained_artifact_ids_must_be_safe_path_components(
    tmp_path: Path, bad_id: str, method: str
) -> None:
    paths = resolve_acquisition_paths(tmp_path, tmp_path / "artifacts")

    with pytest.raises(ValueError):
        getattr(paths, method)(bad_id)


def test_review_target_ids_must_be_safe_path_components(tmp_path: Path) -> None:
    paths = resolve_acquisition_paths(tmp_path, tmp_path / "artifacts")

    with pytest.raises(ValueError):
        paths.review_paths("review-1").case_dir("../escape")


def test_path_resolution_creates_nothing(tmp_path: Path) -> None:
    paths = resolve_acquisition_paths(tmp_path, tmp_path / "artifacts")
    paths.run_dir("run-1")
    paths.run_staging_root("run-1")

    assert list(tmp_path.iterdir()) == []
