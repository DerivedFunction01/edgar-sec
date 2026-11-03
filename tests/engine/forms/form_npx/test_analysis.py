"""Tests for the Form N-PX review analysis."""

from pathlib import Path

from edgar_sec.engine.forms.form_npx.analysis import analyze_case, summarize_cases

_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/npx">
  <headerData><submissionType>N-PX</submissionType></headerData>
  <formData><coverPage>
    <reportingPerson><name>ACME FUND INC</name></reportingPerson>
    <reportInfo><reportType>FUND NOTICE REPORT</reportType></reportInfo>
    <fileNumber>811-00000</fileNumber>
  </coverPage></formData>
</edgarSubmission>
"""


def _case(tmp_path: Path) -> Path:
    case_dir = tmp_path / "0000123456-25-000001--N-PX"
    operations = case_dir / "operations"
    operations.mkdir(parents=True)
    (operations / "render_to_xml.xml").write_bytes(_XML)
    return case_dir


def test_analyze_case_notice_report(tmp_path: Path) -> None:
    """A notice cover yields the companion-document signal only."""
    report = analyze_case(_case(tmp_path))
    assert report is not None
    assert report["anomalies"] == []
    assert report["review_signals"] == ["votes_in_companion_document"]
    assert report["core_fields"]["period_of_report"] is False


def test_summarize_cases() -> None:
    """The summary aggregates vote rows and the scorecard."""
    summary = summarize_cases(
        [
            {
                "core_fields": {"report_type": True},
                "anomalies": [],
                "review_signals": [],
                "vote_rows": 42,
            }
        ]
    )
    assert summary["family"] == "N-PX"
    assert summary["vote_rows_total"] == 42
