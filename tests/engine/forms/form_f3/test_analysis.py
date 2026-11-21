"""Tests for the Form F-3 review analysis."""

from pathlib import Path

from edgar_sec.engine.forms.form_f3.analysis import analyze_case, summarize_cases

_TEXT = """UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
FORM F-3
REGISTRATION STATEMENT UNDER THE SECURITIES ACT OF 1933
File No. 333-211718
THE TORONTO-DOMINION BANK
(Exact name of Registrant as specified in its charter)
CALCULATION OF REGISTRATION FEE
PROSPECTUS SUMMARY
The offering.
RISK FACTORS
Investing in our securities involves risks.
PART II
ITEM 8. INDEMNIFICATION OF DIRECTORS AND OFFICERS
ITEM 10. UNDERTAKINGS
"""


def _case(tmp_path: Path) -> Path:
    case_dir = tmp_path / "0001104659-26-112244--F-3"
    operations = case_dir / "operations"
    operations.mkdir(parents=True)
    (operations / "render_to_txt.txt").write_text(_TEXT, encoding="utf-8")
    return case_dir


def test_analyze_case_cover_fields(tmp_path: Path) -> None:
    """File-number caption, registrant, kind, and fee table extract."""
    report = analyze_case(_case(tmp_path), {"form": "F-3"})
    assert report is not None
    assert report["family"] == "F-3"
    fields = report["form_f3"]
    assert fields["registration_number"] == "333-211718"
    assert fields["registrant_name"] is not None
    assert "TORONTO-DOMINION" in fields["registrant_name"].upper()
    assert fields["document_kind"] == "registration_statement"
    assert fields["fee_table_present"] is True
    kinds = [a["kind"] for a in report["anomalies"]]
    assert "missing_registration_number" not in kinds
    assert "missing_registrant_name" not in kinds


def test_analyze_case_asr_kind(tmp_path: Path) -> None:
    """An F-3ASR case classifies as an automatic shelf registration."""
    report = analyze_case(_case(tmp_path), {"form": "F-3ASR"})
    assert report is not None
    assert report["form_f3"]["document_kind"] == "automatic_shelf_registration"


def test_summarize_cases_builds_scorecard(tmp_path: Path) -> None:
    """The summary builds the form_f3 scorecard from a real report."""
    report = analyze_case(_case(tmp_path), {"form": "F-3"})
    assert report is not None
    summary = summarize_cases([report])
    assert summary["family"] == "F-3"
    scorecard = summary["form_f3_scorecard"]
    assert scorecard["registration_number_count"] == 1
    assert scorecard["fee_table_count"] == 1
