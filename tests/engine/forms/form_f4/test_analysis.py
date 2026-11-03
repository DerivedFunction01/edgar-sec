"""Tests for the Form F-4 review analysis."""

from pathlib import Path

from edgar_sec.engine.forms.form_f4.analysis import analyze_case, summarize_cases

_TEXT = """UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
FORM F-4
REGISTRATION STATEMENT UNDER THE SECURITIES ACT OF 1933
Files Nos. 333-123456, 333-123457
ACME MERGER CORP.
(Exact name of Registrant as specified in its charter)
CALCULATION OF REGISTRATION FEE
PROSPECTUS SUMMARY
The merger.
RISK FACTORS
Investing in our securities involves risks.
PART II
ITEM 20. INDEMNIFICATION OF DIRECTORS AND OFFICERS
ITEM 22. UNDERTAKINGS
"""


def _case(tmp_path: Path) -> Path:
    case_dir = tmp_path / "0001104659-26-112255--F-4"
    operations = case_dir / "operations"
    operations.mkdir(parents=True)
    (operations / "render_to_txt.txt").write_text(_TEXT, encoding="utf-8")
    return case_dir


def test_analyze_case_cover_fields(tmp_path: Path) -> None:
    """Plural Files Nos. caption resolves the first registration number."""
    report = analyze_case(_case(tmp_path), {"form": "F-4"})
    assert report is not None
    assert report["family"] == "F-4"
    fields = report["form_f4"]
    assert fields["registration_number"] == "333-123456"
    assert fields["registrant_name"] is not None
    assert "ACME MERGER" in fields["registrant_name"].upper()
    assert fields["document_kind"] == "registration_statement"
    assert fields["fee_table_present"] is True
    kinds = [a["kind"] for a in report["anomalies"]]
    assert "missing_registration_number" not in kinds
    assert "missing_registrant_name" not in kinds


def test_analyze_case_pos_kind(tmp_path: Path) -> None:
    """An F-4 POS case classifies as a post-effective amendment."""
    report = analyze_case(_case(tmp_path), {"form": "F-4 POS"})
    assert report is not None
    assert report["form_f4"]["document_kind"] == "post_effective_amendment"


def test_summarize_cases_builds_scorecard(tmp_path: Path) -> None:
    """The summary builds the form_f4 scorecard from a real report."""
    report = analyze_case(_case(tmp_path), {"form": "F-4"})
    assert report is not None
    summary = summarize_cases([report])
    assert summary["family"] == "F-4"
    scorecard = summary["form_f4_scorecard"]
    assert scorecard["registration_number_count"] == 1
    assert scorecard["fee_table_count"] == 1
