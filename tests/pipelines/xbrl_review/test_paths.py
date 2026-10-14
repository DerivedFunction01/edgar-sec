"""Tests for XBRL review pipeline paths resolution."""

from pathlib import Path

from edgar_sec.pipelines.xbrl_review.paths import (
    WORK_ORDER_FILE,
    xbrl_paths,
    xbrl_run_paths,
)


def test_xbrl_paths_properties(tmp_path: Path) -> None:
    """Verify standard paths and directory properties."""
    paths = xbrl_paths(artifacts_root=tmp_path)
    assert paths.artifacts_root == tmp_path
    assert paths.review_runs_root == tmp_path / "xbrl" / "review-runs"
    assert paths.snapshots_root == tmp_path / "xbrl" / "snapshots"
    assert (
        paths.unification_rules_db_path
        == tmp_path / "xbrl" / "unification_rules.duckdb"
    )

    rp = paths.review_paths("run-20261014_120000")
    assert rp.root == tmp_path / "xbrl" / "review-runs" / "run-20261014_120000"
    assert rp.cases_dir == rp.root / "cases"
    assert paths.default_seed_cohort_path.name == "seed_cohort.json"
    assert paths.default_sp100_cohort_path.name == "sp100_cohort.json"


def test_xbrl_run_paths_derivation(tmp_path: Path) -> None:
    """Verify XbrlRunPaths derivation for execution run ID."""
    run_p = xbrl_run_paths(tmp_path, "run-20261014_120000")
    assert run_p.run_root == tmp_path / "transient" / "xbrl" / "run-20261014_120000"
    assert run_p.work_order_path().name == WORK_ORDER_FILE
    assert run_p.chunk_dir("0000").name == "0000"
    assert run_p.attempt_dir("0000", "01").name == "attempt-01"
