"""Tests for the Form NSAR review analysis."""

from pathlib import Path

from edgar_sec.engine.forms.form_nsar.analysis import (
    _nsar_fields,
    analyze_case,
    summarize_cases,
)

_TEXT = """PAGE  1
000 B000000 07/31/2011
000 C000000 0001244183
001 A000000 PIMCO INCOME STRATEGY FUND
001 B000000 811-21374
001 C000000 2127393371
008 A000001 ALLIANZ GLOBAL INVESTORS FUND MANAGEMENT LLC
"""


def test_nsar_fields_keyed_answers() -> None:
    """Keyed identity answers extract from the answer-file text."""
    fields = _nsar_fields(_TEXT)
    assert fields["registrant_name"] == "PIMCO INCOME STRATEGY FUND"
    assert fields["file_number"] == "811-21374"
    assert fields["report_period"] == "07/31/2011"
    assert fields["cik"] == "0001244183"
    assert fields["answer_lines"] == 6


def _case(tmp_path: Path) -> Path:
    case_dir = tmp_path / "0001244183-11-000555--NSAR-B"
    operations = case_dir / "operations"
    operations.mkdir(parents=True)
    (operations / "render_to_txt.txt").write_text(_TEXT, encoding="utf-8")
    return case_dir


def test_analyze_case_answers(tmp_path: Path) -> None:
    """A keyed case yields its identity fields in the report."""
    report = analyze_case(_case(tmp_path), {"form": "NSAR-B"})
    assert report is not None
    fields = report["form_nsar"]
    assert fields["registrant_name"] == "PIMCO INCOME STRATEGY FUND"
    kinds = [a["kind"] for a in report["anomalies"]]
    assert "missing_registrant_name" not in kinds
    assert "missing_file_number" not in kinds


def test_summarize_cases(tmp_path: Path) -> None:
    """The summary builds the NSAR scorecard from a real report."""
    report = analyze_case(_case(tmp_path), {"form": "NSAR"})
    assert report is not None
    summary = summarize_cases([report])
    assert summary["family"] == "NSAR"
    assert summary["form_nsar_scorecard"]["answer_lines_total"] == 6
