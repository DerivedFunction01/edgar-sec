"""Tests for XBRL review pipeline paths resolution."""

from pathlib import Path

from edgar_sec.pipelines.xbrl_review.paths import (
    FIXTURES_DIR,
    WORK_ORDER_FILE,
    default_sp100_cohort_path,
    xbrl_paths,
    xbrl_run_paths,
)


def test_xbrl_paths_properties(tmp_path: Path) -> None:
    """Verify standard paths and directory properties."""
    paths = xbrl_paths(artifacts_root=tmp_path)
    assert paths.artifacts_root == tmp_path
    assert paths.fixtures_root == tmp_path / "xbrl" / "fixtures"
    fixture = paths.fixture_paths("golden")
    assert paths.fixture_root("golden") == fixture.root
    assert paths.fixture_manifest_path("golden") == fixture.manifest_path
    assert paths.fixture_database_path("golden") == fixture.storage_path
    assert paths.review_runs_root == tmp_path / "xbrl" / "review-runs"
    assert paths.snapshots_root == tmp_path / "xbrl" / "snapshots"
    assert (
        paths.unification_rules_db_path
        == tmp_path / "xbrl" / "unification_rules.duckdb"
    )

    rp = paths.review_paths("run-20261014_120000")
    assert rp.root == tmp_path / "xbrl" / "review-runs" / "run-20261014_120000"
    assert rp.cases_dir == rp.root / "cases"
    assert paths.builtin_fixtures_dir == FIXTURES_DIR
    assert paths.default_sp100_cohort_path.name == "sp100_cohort.json"
    assert paths.default_sp100_cohort_path.is_file()
    assert default_sp100_cohort_path(tmp_path) == paths.default_sp100_cohort_path


def test_xbrl_run_paths_derivation(tmp_path: Path) -> None:
    """Verify XbrlRunPaths derivation for execution run ID."""
    run_p = xbrl_run_paths(tmp_path, "run-20261014_120000")
    assert run_p.run_root == tmp_path / "transient" / "xbrl" / "run-20261014_120000"
    assert run_p.work_order_path().name == WORK_ORDER_FILE
    assert run_p.chunk_dir("0000").name == "0000"
    assert run_p.attempt_dir("0000", "01").name == "attempt-01"
