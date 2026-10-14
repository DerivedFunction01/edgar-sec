"""Tests for mine_xbrl_lattice CLI tool."""

import json
from pathlib import Path

from edgar_sec.tools.mine_xbrl_lattice import main
from tests.support import fixture_path


def test_mine_xbrl_lattice_cli(tmp_path: Path) -> None:
    """Verify lattice candidate mining CLI with local fixtures."""
    out_json = tmp_path / "mined.json"
    cohort_json = fixture_path("xbrl/seed_cohort.json")
    fixtures_dir = fixture_path("xbrl")
    ret = main(
        [
            "--output",
            str(out_json),
            "--cohort-file",
            str(cohort_json),
            "--fixtures-dir",
            str(fixtures_dir),
            "--min-pmi",
            "0.0",
            "--min-freq",
            "1",
        ]
    )
    assert ret == 0
    assert out_json.exists()
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert "candidate_phrases" in payload
    assert "candidate_relations" in payload


def test_mine_xbrl_lattice_missing_cohort() -> None:
    """Verify non-zero return code when cohort file is missing."""
    ret = main(["--cohort-file", "/nonexistent/cohort.json"])
    assert ret == 1
