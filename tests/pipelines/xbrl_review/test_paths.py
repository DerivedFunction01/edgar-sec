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


def test_xbrl_paths_review_and_snapshot_leaves(tmp_path: Path) -> None:
    """Verify review-case and snapshot relation leaf paths."""
    paths = xbrl_paths(artifacts_root=tmp_path)
    run_root = tmp_path / "xbrl" / "review-runs" / "run-1"
    assert paths.review_manifest_path("run-1") == run_root / "manifest.jsonl"
    case_dir = run_root / "cases" / "0000000001-26-000001"
    assert paths.review_case_dir("run-1", "0000000001-26-000001") == case_dir
    assert (
        paths.review_case_solved_nodes_path("run-1", "0000000001-26-000001")
        == case_dir / "solved_nodes.parquet"
    )
    assert (
        paths.review_case_rule_trace_path("run-1", "0000000001-26-000001")
        == case_dir / "rule_trace.parquet"
    )
    assert (
        paths.review_case_quarantine_path("run-1", "0000000001-26-000001")
        == case_dir / "quarantine.parquet"
    )
    assert (
        paths.review_case_hypotheses_path("run-1", "0000000001-26-000001")
        == case_dir / "hypotheses.parquet"
    )
    assert (
        paths.review_case_presentation_arcs_path("run-1", "0000000001-26-000001")
        == case_dir / "presentation_arcs.parquet"
    )
    assert (
        paths.review_case_calculation_arcs_path("run-1", "0000000001-26-000001")
        == case_dir / "calculation_arcs.parquet"
    )
    relation_dir = tmp_path / "xbrl" / "snapshots" / "snapshot-1" / "solved_nodes"
    assert paths.snapshot_relation_dir("snapshot-1", "solved_nodes") == relation_dir
    assert (
        paths.snapshot_part_path("snapshot-1", "solved_nodes", 0)
        == relation_dir / "part-00000.parquet"
    )


def test_xbrl_run_paths_derivation(tmp_path: Path) -> None:
    """Verify XbrlRunPaths derivation for execution run ID."""
    run_p = xbrl_run_paths(tmp_path, "run-20261014_120000")
    assert run_p.run_root == tmp_path / "transient" / "xbrl" / "run-20261014_120000"
    assert run_p.work_order_path().name == WORK_ORDER_FILE
    assert run_p.chunk_dir("0000").name == "0000"
    assert run_p.attempt_dir("0000", "01").name == "attempt-01"
