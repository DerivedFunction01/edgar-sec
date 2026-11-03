"""Tests for the Form N-CSR review analysis."""

from pathlib import Path

from edgar_sec.engine.forms.form_ncsr.analysis import analyze_case, summarize_cases

_TEXT = """UNITED STATES SECURITIES AND EXCHANGE COMMISSION
FORM N-CSR
CERTIFIED SHAREHOLDER REPORT OF REGISTERED MANAGEMENT INVESTMENT COMPANIES
Investment Company Act file number  811-06495
Flaherty & Crumrine Preferred Income Opportunity Fund Incorporated
(Exact name of registrant as specified in charter)
For the semi-annual period ended May 31, 2018
PORTFOLIO OF INVESTMENTS
STATEMENT OF ASSETS AND LIABILITIES
FINANCIAL HIGHLIGHTS
"""


def _case(tmp_path: Path) -> Path:
    case_dir = tmp_path / "0000882071-18-000294--N-CSR"
    operations = case_dir / "operations"
    operations.mkdir(parents=True)
    (operations / "render_to_txt.txt").write_text(_TEXT, encoding="utf-8")
    return case_dir


def test_analyze_case_cover(tmp_path: Path) -> None:
    """A covered case yields file number and registrant identity."""
    report = analyze_case(_case(tmp_path), {"form": "N-CSR"})
    assert report is not None
    fields = report["form_ncsr"]
    assert fields["file_number"] == "811-06495"
    assert fields["registrant_name"].startswith("Flaherty")
    assert fields["report_period"] == "May 31, 2018"
    kinds = [a["kind"] for a in report["anomalies"]]
    assert "missing_file_number" not in kinds
    assert "missing_registrant_name" not in kinds


def test_summarize_cases(tmp_path: Path) -> None:
    """The summary builds the N-CSR scorecard from a real report."""
    report = analyze_case(_case(tmp_path), {"form": "N-CSR"})
    assert report is not None
    summary = summarize_cases([report])
    assert summary["family"] == "N-CSR"
    assert summary["form_ncsr_scorecard"]["file_number_count"] == 1
