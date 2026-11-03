"""Tests for the Form N-Q review analysis."""

from pathlib import Path

from edgar_sec.engine.forms.form_nq.analysis import analyze_case, summarize_cases

_TEXT = """UNITED STATES SECURITIES AND EXCHANGE COMMISSION
FORM N-Q
QUARTERLY SCHEDULE OF PORTFOLIO HOLDINGS
Investment Company Act file number  811-06495
Flaherty & Crumrine Preferred Income Opportunity Fund Incorporated
(Exact name of registrant as specified in charter)
SCHEDULE OF INVESTMENTS
CONTROLS AND PROCEDURES
"""


def _case(tmp_path: Path) -> Path:
    case_dir = tmp_path / "0000882071-18-000294--N-Q"
    operations = case_dir / "operations"
    operations.mkdir(parents=True)
    (operations / "render_to_txt.txt").write_text(_TEXT, encoding="utf-8")
    return case_dir


def test_analyze_case_cover(tmp_path: Path) -> None:
    """A covered case yields file number and registrant identity."""
    report = analyze_case(_case(tmp_path), {"form": "N-Q"})
    assert report is not None
    fields = report["form_nq"]
    assert fields["file_number"] == "811-06495"
    assert fields["registrant_name"].startswith("Flaherty")
    kinds = [a["kind"] for a in report["anomalies"]]
    assert "missing_file_number" not in kinds
    assert "missing_registrant_name" not in kinds


def test_summarize_cases(tmp_path: Path) -> None:
    """The summary builds the N-Q scorecard from a real report."""
    report = analyze_case(_case(tmp_path), {"form": "N-Q"})
    assert report is not None
    summary = summarize_cases([report])
    assert summary["family"] == "N-Q"
    assert summary["form_nq_scorecard"]["file_number_count"] == 1
