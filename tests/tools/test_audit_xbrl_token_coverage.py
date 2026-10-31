"""Tests for audit_xbrl_token_coverage CLI tool."""

import json
from pathlib import Path
import shutil

from edgar_sec.tools.audit_xbrl_token_coverage import main
from tests.support import fixture_path


def test_audit_cli_over_one_bundle(tmp_path: Path) -> None:
    """Verify the audit CLI writes a report for the bundles it finds."""
    fixtures_dir = tmp_path / "seed"
    fixtures_dir.mkdir()
    source = fixture_path("xbrl/seed/msft_2024_10k")
    shutil.copytree(source, fixtures_dir / "msft_2024_10k")

    out_json = tmp_path / "report.json"
    ret = main(
        [
            "--output",
            str(out_json),
            "--cohort-file",
            str(fixture_path("xbrl/seed_cohort.json")),
            "--fixtures-dir",
            str(fixtures_dir),
        ]
    )
    assert ret == 0
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["total_concepts"] > 100
    assert payload["total_fact_rows"] > 1000
    assert sum(dict(payload["bucket_counts"]).values()) == payload["total_concepts"]
    assert payload["candidates"]


def test_audit_cli_missing_cohort() -> None:
    """Verify non-zero return code when the cohort file is missing."""
    ret = main(["--cohort-file", "/nonexistent/cohort.json"])
    assert ret == 1
