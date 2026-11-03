"""Tests for the F-N review analysis."""

from pathlib import Path

from edgar_sec.engine.forms.form_fn.analysis import analyze_case, summarize_cases

_FN_TEXT = """UNITED STATES SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
FORM F-N
APPOINTMENT OF AGENT FOR SERVICE OF PROCESS
A. Name of issuer or person filing ("Filer"): The Toronto-Dominion Bank
B. This is (select one):
[X] an original filing for the Filer
[ ] an amended filing for the Filer
C. Identify the filing in conjunction with which this form is being filed:
Name of registrant: The Toronto-Dominion Bank
Form type: Registration Statement on Form F-3
File Number (if known): 333-211718
Filed by: The Toronto-Dominion Bank
Date Filed (if filed concurrently, so indicate): Concurrently
D. The Filer is incorporated or organized under the laws of Canada and
has its principal place of business at Toronto, Ontario.
E. The Filer designates and appoints Glenn Gibson ("Agent") located at
31 West 52nd Street, New York, NY as the agent of the Filer.
F. Successor agent stipulation and undertaking
G. Undertaking to respond to Commission staff inquiries
"""


def _case(tmp_path: Path, text: str) -> Path:
    case_dir = tmp_path / "case"
    operations = case_dir / "operations"
    operations.mkdir(parents=True)
    (operations / "render_to_txt.txt").write_text(text, encoding="utf-8")
    return case_dir


def test_analyze_fn_fields(tmp_path: Path) -> None:
    """The lettered fields resolve: filer, kind, conjunction, agent."""
    report = analyze_case(_case(tmp_path, _FN_TEXT), {"form": "F-N"})
    assert report is not None
    fields = report["form_fn"]
    assert fields["filer_name"] == "The Toronto-Dominion Bank"
    assert fields["filing_kind"] == ["original_filing"]
    assert fields["conjunction_form_type"] == "Registration Statement on Form F-3"
    assert fields["conjunction_file_number"] == "333-211718"
    assert fields["jurisdiction"] == "Canada"
    assert fields["agent_name"] == "Glenn Gibson"
    assert set(fields["lettered_items_present"]) == set("ABCDEFG")
    kinds = [a["kind"] for a in report["anomalies"]]
    assert "missing_filer_name" not in kinds
    assert "missing_agent_name" not in kinds
    assert "missing_filing_kind" not in kinds


def test_summarize_cases_scorecard(tmp_path: Path) -> None:
    """The summary aggregates the field census."""
    report = analyze_case(_case(tmp_path, _FN_TEXT), {"form": "F-N"})
    assert report is not None
    summary = summarize_cases([report])
    card = summary["form_fn_scorecard"]
    assert card["case_count"] == 1
    assert card["filer_name_count"] == 1
    assert card["agent_name_count"] == 1
    assert card["filing_kind_counts"] == {"original_filing": 1}
