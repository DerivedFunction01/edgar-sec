"""Tests for XBRL review pipeline paths resolution."""

from pathlib import Path

from edgar_sec.pipelines.xbrl_review.paths import resolve_xbrl_review_paths


def test_resolve_xbrl_review_paths(tmp_path: Path) -> None:
    """Verify standard paths and directory creation."""
    paths = resolve_xbrl_review_paths(artifacts_root=tmp_path)
    assert paths.artifacts_root == tmp_path
    assert paths.review_runs_dir == tmp_path / "xbrl" / "review-runs"
    assert paths.staging_lake_dir == tmp_path / "xbrl" / "staging_lake"
    assert paths.unification_rules_db_path == tmp_path / "xbrl" / "unification_rules.duckdb"

    paths.ensure_directories()
    assert paths.review_runs_dir.is_dir()
    assert paths.staging_lake_dir.is_dir()


def test_review_run_paths(tmp_path: Path) -> None:
    """Verify ReviewPaths derivation for chronological run ID."""
    paths = resolve_xbrl_review_paths(artifacts_root=tmp_path)
    rp = paths.review_run_paths("run-20261014_120000")
    assert rp.root == tmp_path / "xbrl" / "review-runs" / "run-20261014_120000"
    assert rp.cases_dir == rp.root / "cases"
