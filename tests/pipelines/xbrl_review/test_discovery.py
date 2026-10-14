"""Tests for XBRL review discovery of cohorts and runs."""

from pathlib import Path

from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.pipelines.xbrl_review.discovery import (
    discover_cohorts,
    discover_review_runs,
)
from edgar_sec.pipelines.xbrl_review.paths import resolve_xbrl_review_paths


def test_discover_cohorts() -> None:
    """Verify standard seed and S&P 100 cohorts are discovered."""
    cohorts = discover_cohorts()
    ids = [c["cohort_id"] for c in cohorts]
    assert "seed" in ids
    assert "sp100" in ids


def test_discover_review_runs(tmp_path: Path) -> None:
    """Verify discovery of historical run directories and manifests."""
    paths = resolve_xbrl_review_paths(artifacts_root=tmp_path)
    run_dir = paths.review_runs_dir / "run-20261014_100000"
    run_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        run_dir / "manifest.jsonl",
        {"run_id": "run-20261014_100000", "total_filings": 5, "total_hypotheses": 2},
    )

    discovered = discover_review_runs(artifacts_root=tmp_path)
    assert len(discovered) == 1
    assert discovered[0]["run_id"] == "run-20261014_100000"
    assert discovered[0]["total_filings"] == 5
