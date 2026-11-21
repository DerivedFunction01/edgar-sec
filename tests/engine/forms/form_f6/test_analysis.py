"""Tests for the F-6 review analysis."""

from pathlib import Path

from edgar_sec.engine.forms.form_f6.analysis import analyze_case, summarize_cases

_F6_TEXT = """As filed with the Commission on January 21, 2022.
Registration No. 333-260123
UNITED STATES SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
FORM F-6
REGISTRATION STATEMENT UNDER THE SECURITIES ACT OF 1933 FOR
DEPOSITARY SHARES EVIDENCED BY AMERICAN DEPOSITARY RECEIPTS
SHELL PLC
(Exact name of issuer of deposited securities as specified in its charter)
England and Wales
(Jurisdiction of incorporation or organization of issuer)
JPMORGAN CHASE BANK, N.A.
(Exact name of depositary as specified in its charter)
It is proposed that this filing shall become effective (check the
appropriate box):
[X] immediately upon filing
CALCULATION OF REGISTRATION FEE
PART I
ITEM 1. DESCRIPTION OF SECURITIES TO BE REGISTERED
ITEM 2. AVAILABLE INFORMATION
PART II
ITEM 3. EXHIBITS
ITEM 4. UNDERTAKINGS
"""


def _case(tmp_path: Path, text: str) -> Path:
    case_dir = tmp_path / "case"
    operations = case_dir / "operations"
    operations.mkdir(parents=True)
    (operations / "render_to_txt.txt").write_text(text, encoding="utf-8")
    return case_dir


def test_analyze_f6_dual_party(tmp_path: Path) -> None:
    """Both cover parties and the Rule 466 decision resolve."""
    report = analyze_case(_case(tmp_path, _F6_TEXT), {"form": "F-6"})
    assert report is not None
    fields = report["form_f6"]
    assert fields["issuer_name"] is not None
    assert "SHELL" in fields["issuer_name"].upper()
    assert fields["depositary_name"] is not None
    assert "JPMORGAN" in fields["depositary_name"].upper()
    assert fields["registration_number"] == "333-260123"
    assert fields["rule_466_decision"] == ["rule_466_immediate"]
    kinds = [a["kind"] for a in report["anomalies"]]
    assert "missing_issuer_name" not in kinds
    assert "missing_depositary_name" not in kinds
    assert "missing_rule_466_decision" not in kinds


def test_summarize_cases_scorecard(tmp_path: Path) -> None:
    """The summary groups F-6 scorecard counts per family."""
    report = analyze_case(_case(tmp_path, _F6_TEXT), {"form": "F-6"})
    assert report is not None
    summary = summarize_cases([report])
    card = summary["form_f6_scorecard"]["F-6"]
    assert card["case_count"] == 1
    assert card["issuer_name_count"] == 1
    assert card["depositary_name_count"] == 1
    assert card["rule_466_decision_count"] == 1
