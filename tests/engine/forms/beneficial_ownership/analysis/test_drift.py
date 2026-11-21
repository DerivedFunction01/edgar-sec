"""Unit tests for the beneficial ownership anomaly drift comparison tool."""

from __future__ import annotations

import json
from pathlib import Path

from edgar_sec.engine.forms.beneficial_ownership.analysis.drift import (
    compare_audit_summaries,
    format_drift_report,
)


def test_compare_audit_summaries_detects_fixed_and_regressions(tmp_path: Path) -> None:
    """Verify categorization of fixed, remaining, and regressed anomalies."""
    base_summary = {
        "anomalies": [
            {
                "accession": "0000000001-24-000001",
                "kind": "invalid_cusip",
                "field": "issuerCusip",
            },
            {
                "accession": "0000000002-24-000002",
                "kind": "cover_field_contamination",
                "field": "reportingPersonName",
            },
        ]
    }
    cand_summary = {
        "anomalies": [
            {
                "accession": "0000000002-24-000002",
                "kind": "cover_field_contamination",
                "field": "reportingPersonName",
            },
            {
                "accession": "0000000003-24-000003",
                "kind": "invalid_date",
                "field": "eventDate",
            },
        ]
    }

    base_file = tmp_path / "base.json"
    cand_file = tmp_path / "cand.json"
    base_file.write_text(json.dumps(base_summary), encoding="utf-8")
    cand_file.write_text(json.dumps(cand_summary), encoding="utf-8")

    report = compare_audit_summaries(base_file, cand_file)

    assert report.baseline_count == 2
    assert report.candidate_count == 2
    assert report.net_change == 0
    assert report.has_regressions is True

    assert len(report.fixed) == 1
    assert report.fixed[0]["accession"] == "0000000001-24-000001"
    assert report.fixed_by_kind == {"invalid_cusip": 1}

    assert len(report.remaining) == 1
    assert report.remaining[0]["accession"] == "0000000002-24-000002"

    assert len(report.regressions) == 1
    assert report.regressions[0]["accession"] == "0000000003-24-000003"
    assert report.regressions_by_kind == {"invalid_date": 1}

    formatted = format_drift_report(report)
    assert "[FIXED] Anomalies by Kind:" in formatted
    assert "[REGRESSION] New Anomalies:" in formatted
    assert "[REMAINING] Known Anomalies by Kind:" in formatted


def test_compare_audit_summaries_clean_run_with_no_regressions() -> None:
    """Verify report metrics when all anomalies are resolved without regressions."""
    base_summary = {
        "anomalies": [
            {"accession": "0000000001-24-000001", "kind": "invalid_cusip"},
        ]
    }
    cand_summary = {"anomalies": []}

    report = compare_audit_summaries(base_summary, cand_summary)

    assert report.baseline_count == 1
    assert report.candidate_count == 0
    assert report.net_change == -1
    assert report.has_regressions is False
    assert len(report.fixed) == 1
    assert len(report.regressions) == 0
