"""Tests for the MJDS review analysis."""

from pathlib import Path

from edgar_sec.engine.forms.form_mjds.analysis import analyze_case, summarize_cases

_F10_TEXT = """UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
FORM F-10
REGISTRATION STATEMENT UNDER THE SECURITIES ACT OF 1933
Registration No. 333-209831
THE TORONTO-DOMINION BANK
(Exact name of Registrant as specified in its charter)
It is proposed that this filing shall become effective (check the
appropriate box):
[X] upon filing with the Commission, pursuant to Rule 467(a)
CALCULATION OF REGISTRATION FEE
RISK FACTORS
Investing in our securities involves risks.
USE OF PROCEEDS
The net proceeds will be used for general corporate purposes.
PART II
ITEM 1. UNDERTAKINGS
ITEM 2. CONSENT TO SERVICE OF PROCESS
"""

_F7_TEXT = """UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
FORM F-7
REGISTRATION STATEMENT UNDER THE SECURITIES ACT OF 1933
Registration No. 333-171902
TECK RESOURCES LIMITED
(Exact name of Registrant as specified in its charter)
The home jurisdiction prospectus is furnished as part of this
registration statement.
PART II
ITEM 1. HOME JURISDICTION DOCUMENTS
ITEM 4. LIST OF DOCUMENTS FILED
"""


def _case(tmp_path: Path, text: str) -> Path:
    case_dir = tmp_path / "case"
    operations = case_dir / "operations"
    operations.mkdir(parents=True)
    (operations / "render_to_txt.txt").write_text(text, encoding="utf-8")
    return case_dir


def test_analyze_f10_election_and_prospectus(tmp_path: Path) -> None:
    """Election resolves from the checked box; prospectus headings census."""
    report = analyze_case(_case(tmp_path, _F10_TEXT), {"form": "F-10"})
    assert report is not None
    assert report["family"] == "F-10"
    fields = report["form_mjds"]
    assert fields["registration_number"] == "333-209831"
    assert fields["registrant_name"] is not None
    assert "TORONTO-DOMINION" in fields["registrant_name"].upper()
    assert fields["effectiveness_election"] == ["rule_467a_upon_filing"]
    assert "risk factors" in fields["prospectus_headings"]
    assert "use of proceeds" in fields["prospectus_headings"]
    kinds = [a["kind"] for a in report["anomalies"]]
    assert "missing_effectiveness_election" not in kinds


def test_analyze_f7_home_jurisdiction_tail(tmp_path: Path) -> None:
    """F-7 rides the shared analyzer; its family resolves via the alias map."""
    report = analyze_case(_case(tmp_path, _F7_TEXT), {"form": "F-7"})
    assert report is not None
    assert report["family"] == "F-7"
    fields = report["form_mjds"]
    assert fields["registration_number"] == "333-171902"
    assert "TECK" in (fields["registrant_name"] or "").upper()
    assert "prospectus_headings" not in fields


def test_summarize_cases_groups_by_family(tmp_path: Path) -> None:
    """The summary groups MJDS scorecards per family."""
    f10 = analyze_case(_case(tmp_path, _F10_TEXT), {"form": "F-10"})
    assert f10 is not None
    summary = summarize_cases([f10])
    scorecard = summary["form_mjds_scorecard"]
    assert scorecard["F-10"]["case_count"] == 1
    assert scorecard["F-10"]["election_decision_count"] == 1
    assert scorecard["F-10"]["registration_number_count"] == 1
    assert scorecard["F-10"]["prospectus_heading_counts"]["risk factors"] == 1
