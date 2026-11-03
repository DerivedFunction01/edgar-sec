"""Tests for the Form 497 review analysis."""

from pathlib import Path

from edgar_sec.engine.forms.form_497.analysis import analyze_case, summarize_cases

_TEXT = """Filed pursuant to Rule 497(h)
Registration No. 333-91744
PROSPECTUS
PIMCO Municipal Income Fund II
Investment Objective. The Fund is a recently organized fund.
USE OF PROCEEDS
LEGAL MATTERS
"""


def _case(tmp_path: Path) -> Path:
    case_dir = tmp_path / "0001170299-02-004212--497"
    operations = case_dir / "operations"
    operations.mkdir(parents=True)
    (operations / "render_to_txt.txt").write_text(_TEXT, encoding="utf-8")
    return case_dir


def test_analyze_case_header(tmp_path: Path) -> None:
    """Rule reference, registration number, and kind extract."""
    report = analyze_case(_case(tmp_path), {"form": "497"})
    assert report is not None
    fields = report["form_497"]
    assert fields["rule_reference"] == "497(h)"
    assert fields["registration_numbers"] == ["333-91744"]
    assert fields["document_kind"] == "prospectus"
    kinds = [a["kind"] for a in report["anomalies"]]
    assert "missing_document_kind" not in kinds


def test_summarize_cases(tmp_path: Path) -> None:
    """The summary builds the 497 scorecard from a real report."""
    report = analyze_case(_case(tmp_path), {"form": "497"})
    assert report is not None
    summary = summarize_cases([report])
    assert summary["family"] == "497"
    assert summary["form_497_scorecard"]["rule_reference_count"] == 1
