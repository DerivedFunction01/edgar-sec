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


def test_analyze_case_kind_beyond_head_window(tmp_path: Path) -> None:
    """A kind term named only in the body still classifies the document;
    a document naming no kind term stays unclassified.
    """
    header = "\n".join(f"Header line {i} of a pricing release" for i in range(45))
    body = "The offering is made only by means of a prospectus supplement."
    case_dir = tmp_path / "pricing"
    operations = case_dir / "operations"
    operations.mkdir(parents=True)
    (operations / "render_to_txt.txt").write_text(
        header + "\n" + body, encoding="utf-8"
    )
    report = analyze_case(case_dir, {"form": "497"})
    assert report is not None
    assert report["form_497"]["document_kind"] == "prospectus_supplement"

    bare_dir = tmp_path / "bare"
    bare_ops = bare_dir / "operations"
    bare_ops.mkdir(parents=True)
    (bare_ops / "render_to_txt.txt").write_text(header, encoding="utf-8")
    bare = analyze_case(bare_dir, {"form": "497"})
    assert bare is not None
    assert bare["form_497"]["document_kind"] is None
    assert "missing_document_kind" in [a["kind"] for a in bare["anomalies"]]


def test_summarize_cases(tmp_path: Path) -> None:
    """The summary builds the 497 scorecard from a real report."""
    report = analyze_case(_case(tmp_path), {"form": "497"})
    assert report is not None
    summary = summarize_cases([report])
    assert summary["family"] == "497"
    assert summary["form_497_scorecard"]["rule_reference_count"] == 1
