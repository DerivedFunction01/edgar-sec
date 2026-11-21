"""Tests for the Forms F-1/F-2 review analysis."""

from pathlib import Path

from edgar_sec.engine.forms.form_f1.analysis import analyze_case, summarize_cases

_TEXT = """UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
FORM F-1
REGISTRATION STATEMENT UNDER THE SECURITIES ACT OF 1933
Registration No. 333-287547
NEW FOUND GOLD CORP.
(Exact name of Registrant as specified in its charter)
CALCULATION OF REGISTRATION FEE
PROSPECTUS SUMMARY
The offering.
RISK FACTORS
Investing in our securities involves risks.
PART II
ITEM 6. INDEMNIFICATION OF DIRECTORS AND OFFICERS
ITEM 9. UNDERTAKINGS
"""


def _case(tmp_path: Path) -> Path:
    case_dir = tmp_path / "0001104659-26-112233--F-1"
    operations = case_dir / "operations"
    operations.mkdir(parents=True)
    (operations / "render_to_txt.txt").write_text(_TEXT, encoding="utf-8")
    return case_dir


def test_analyze_case_cover_fields(tmp_path: Path) -> None:
    """Registration number, registrant, kind, and fee table extract."""
    report = analyze_case(_case(tmp_path), {"form": "F-1"})
    assert report is not None
    assert report["family"] == "F-1"
    fields = report["form_f1"]
    assert fields["registration_number"] == "333-287547"
    assert fields["registrant_name"] is not None
    assert "NEW FOUND GOLD" in fields["registrant_name"].upper()
    assert fields["document_kind"] == "registration_statement"
    assert fields["fee_table_present"] is True
    kinds = [a["kind"] for a in report["anomalies"]]
    assert "missing_registration_number" not in kinds
    assert "missing_registrant_name" not in kinds


def test_analyze_case_f2_amendment_resolves_variant_family(
    tmp_path: Path,
) -> None:
    """An F-2/A case resolves to the F-2 variant of the shared analyzer."""
    report = analyze_case(_case(tmp_path), {"form": "F-2/A"})
    assert report is not None
    assert report["family"] == "F-2"
    assert report["form_f1"]["document_kind"] == "amendment"


def test_summarize_cases_builds_scorecard(tmp_path: Path) -> None:
    """The summary builds the form_f1 scorecard from a real report."""
    report = analyze_case(_case(tmp_path), {"form": "F-1"})
    assert report is not None
    summary = summarize_cases([report])
    assert summary["family"] == "F-1"
    scorecard = summary["form_f1_scorecard"]
    assert scorecard["registration_number_count"] == 1
    assert scorecard["registrant_name_count"] == 1
    assert scorecard["fee_table_count"] == 1
    assert scorecard["document_kind_counts"] == {"registration_statement": 1}
