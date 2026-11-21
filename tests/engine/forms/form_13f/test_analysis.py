"""Tests for the Form 13F review analyzer."""

from pathlib import Path

from edgar_sec.domain.forms.families.form_13f.models import (
    Form13FDocument,
    InfoTableRow,
)
from edgar_sec.engine.forms.form_13f.analysis import analyze_case, summarize_cases
from edgar_sec.engine.forms.form_13f.renderer import build_form_13f_xml

_ROW = InfoTableRow(
    name_of_issuer="ACME CORP",
    title_of_class="COM",
    cusip="001000000",
    value=1250,
    shares_or_principal=100,
    amount_type="SH",
    investment_discretion="SOLE",
    voting_sole=100,
    voting_shared=0,
    voting_none=0,
)


def _case_dir(tmp_path: Path, doc: Form13FDocument) -> Path:
    case_dir = tmp_path / "0000000000-01-000001--abcdef"
    operations = case_dir / "operations"
    operations.mkdir(parents=True)
    output = build_form_13f_xml(doc)
    (operations / "render_to_xml.xml").write_bytes(output.content)
    return case_dir


def test_analyze_complete_document(tmp_path: Path) -> None:
    """Rows matching the stated totals produce no completeness signals."""
    doc = Form13FDocument(
        submission_type="13F-HR",
        manager_name="ACME ADVISORS",
        holdings=(_ROW,),
        period_of_report="December 31, 2001",
        report_type="13F HOLDINGS REPORT",
        table_entry_total=1,
        table_value_total=1250,
    )
    report = analyze_case(_case_dir(tmp_path, doc))
    assert report is not None
    assert report["anomalies"] == []
    assert report["review_signals"] == []
    assert report["holdings_rows"] == 1
    assert report["core_fields"]["manager_name"] is True


def test_analyze_completeness_mismatch_signals(tmp_path: Path) -> None:
    """Row and value totals that disagree with the rows become signals."""
    doc = Form13FDocument(
        submission_type="13F-HR",
        manager_name="ACME ADVISORS",
        holdings=(_ROW,),
        period_of_report="December 31, 2001",
        report_type="13F HOLDINGS REPORT",
        table_entry_total=93,
        table_value_total=999999,
    )
    report = analyze_case(_case_dir(tmp_path, doc))
    assert report is not None
    signals = report["review_signals"]
    assert any(s.startswith("holdings_count_mismatch") for s in signals)
    assert any(s.startswith("holdings_value_mismatch") for s in signals)


def test_analyze_submission_only_signals_companion(tmp_path: Path) -> None:
    """A submission without rows signals the companion-document shape."""
    doc = Form13FDocument(
        submission_type="13F-HR",
        manager_name="ACME ADVISORS",
        holdings=(),
        period_of_report="12-31-2025",
        report_type="13F HOLDINGS REPORT",
        table_entry_total=10,
        table_value_total=5000,
    )
    report = analyze_case(_case_dir(tmp_path, doc))
    assert report is not None
    assert report["review_signals"] == ["holdings_in_companion_document"]


def test_summarize_cases() -> None:
    """The summary aggregates scorecard, anomalies, and row totals."""
    reports = [
        {
            "core_fields": {"manager_name": True},
            "anomalies": ["missing_report_type"],
            "review_signals": [],
            "holdings_rows": 3,
        }
    ]
    summary = summarize_cases(reports)
    assert summary["family"] == "13F"
    assert summary["case_count"] == 1
    assert summary["anomaly_count"] == 1
    assert summary["holdings_rows_total"] == 3
