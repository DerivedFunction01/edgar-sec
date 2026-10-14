"""Tests for validate_xbrl_benchmark CLI tool."""

import json
from pathlib import Path

from edgar_sec.tools.validate_xbrl_benchmark import main
from tests.support import fixture_path


def test_validate_xbrl_benchmark_cli(tmp_path: Path) -> None:
    """Verify multi-firm robustness benchmark CLI passes 100% on seed cohort."""
    out_json = tmp_path / "benchmark.json"
    cohort_json = fixture_path("xbrl/seed_cohort.json")
    tax_dir = fixture_path("xbrl/taxonomy")
    ret = main(
        [
            "--output",
            str(out_json),
            "--cohort-file",
            str(cohort_json),
            "--taxonomy-dir",
            str(tax_dir),
        ]
    )
    assert ret == 0
    assert out_json.exists()
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    summary = payload["summary"]
    assert summary["accuracy_pct"] == 100.0
    assert summary["failed_tests"] == 0
    assert summary["passed_tests"] > 0
    assert summary["firm_count"] == 15


def test_validate_xbrl_benchmark_missing_cohort() -> None:
    """Verify non-zero return code when cohort file is missing."""
    ret = main(["--cohort-file", "/nonexistent/cohort.json"])
    assert ret == 1
