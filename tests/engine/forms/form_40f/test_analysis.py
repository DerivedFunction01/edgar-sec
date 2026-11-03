"""Tests for the Form 40-F review analysis."""

from pathlib import Path

from edgar_sec.engine.forms.form_40f.analysis import analyze_case, summarize_cases

_TEXT = """UNITED STATES SECURITIES AND EXCHANGE COMMISSION

Washington, D.C. 20549

FORM 40-F

(Check One)

[ ] Registration statement pursuant to Section 12 of the Securities Exchange Act of 1934

[X] Annual report pursuant to Section 13(a) or 15(d) of the Securities Exchange Act of 1934

For fiscal year ended: December 31, 2025 Commission File number: 1-31402

BCE INC.

(Exact name of Registrant as specified in its charter)

Canada

(Province or Other Jurisdiction of Incorporation or Organization)

For annual reports, indicate by check mark the information filed with this form:

[X] Annual Information Form [X] Audited Annual Financial Statements

MANAGEMENT'S DISCUSSION AND ANALYSIS

Discussion of results for the year.

ANNUAL INFORMATION FORM

Corporate structure and general development of the business.
"""


def _case(tmp_path: Path) -> Path:
    case_dir = tmp_path / "case"
    operations = case_dir / "operations"
    operations.mkdir(parents=True)
    (operations / "render_to_txt.txt").write_text(_TEXT, encoding="utf-8")
    return case_dir


def test_analyze_case_election_and_furnished(tmp_path: Path) -> None:
    """Election resolves to the annual-report box; furnished kinds segment."""
    report = analyze_case(_case(tmp_path), {"form": "40-F"})
    assert report is not None
    assert report["family"] == "40-F"
    fields = report["form_40f"]
    assert fields["election"] == ["section_13a_15d_annual_report"]
    assert "aif" in fields["furnished_segments"]
    assert "mda" in fields["furnished_segments"]
    kinds = [a["kind"] for a in report["anomalies"]]
    assert "missing_election_decision" not in kinds


def test_summarize_cases_builds_scorecard(tmp_path: Path) -> None:
    """The summary builds the form_40f scorecard from a real report."""
    report = analyze_case(_case(tmp_path), {"form": "40-F"})
    assert report is not None
    summary = summarize_cases([report])
    scorecard = summary["form_40f_scorecard"]
    assert scorecard["election_decision_count"] == 1
    assert scorecard["election_counts"]["section_13a_15d_annual_report"] == 1
    assert scorecard["furnished_segment_counts"]["aif"] == 1


_40F_ERA_TITLE_TEXT = """U.S. Securities and Exchange Commission
Washington, D.C. 20549
Form 40-F
Annual report pursuant to section 13(a) or 15(d) of the Securities Exchange Act of 1934
For the fiscal year ended December 31, 2004 Commission File Number: 1-31556
FAIRFAX FINANCIAL HOLDINGS LIMITED
(Exact name of Registrant as specified in its charter)
Canada
(Province or other jurisdiction of incorporation or organization)
ANNUAL INFORMATION FORM
The annual information form is furnished as an exhibit.
"""


def _case_text(tmp_path: Path, text: str) -> Path:
    case_dir = tmp_path / "case-title"
    operations = case_dir / "operations"
    operations.mkdir(parents=True)
    (operations / "render_to_txt.txt").write_text(text, encoding="utf-8")
    return case_dir


def test_analyze_40f_title_declared_election(tmp_path: Path) -> None:
    """An era cover's subtitle line declares the election directly."""
    report = analyze_case(_case_text(tmp_path, _40F_ERA_TITLE_TEXT), {"form": "40-F"})
    assert report is not None
    fields = report["form_40f"]
    assert fields["election"] == ["section_13a_15d_annual_report"]
    assert fields["election_source"] == "title"
    kinds = [a["kind"] for a in report["anomalies"]]
    assert "missing_election_decision" not in kinds
