from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.forms.form_425.analysis import analyze_case, summarize_cases

_SAMPLE_425_TEXT = """\
Filed by: Acme Holdings Corporation

Pursuant to Rule 425 under the Securities Act of 1933
and deemed filed pursuant to Rule 14a-12
under the Securities Exchange Act of 1934

Subject Company: Widget Industries, Inc.
Commission File No.: 001-37785

Acme Holdings and Widget Industries announce merger agreement.

The combined company will be a leader in widget manufacturing.
"""


def _write_case(tmp_path: Path, text: str) -> None:
    ops = tmp_path / "operations"
    ops.mkdir(parents=True)
    (ops / "render_to_txt.txt").write_text(text, encoding="utf-8")


def test_analyze_case_missing_artifact(tmp_path: Path) -> None:
    result = analyze_case(tmp_path, {"accession": "0000000000-00-000000"})
    assert result is None


def test_analyze_case_425_header(tmp_path: Path) -> None:
    _write_case(tmp_path, _SAMPLE_425_TEXT)

    result = analyze_case(
        tmp_path, {"accession": "0000006955-22-000016", "form": "425"}
    )
    assert result is not None
    assert result["family"] == "425"
    fields = result["form_425"]
    assert fields["filer_name"] == "Acme Holdings Corporation"
    assert fields["subject_company"] == "Widget Industries, Inc."
    assert fields["commission_file_number"] == "001-37785"
    assert fields["rule_425"] is True
    assert fields["rule_14a_12"] is True
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_filer_name" not in kinds
    assert "missing_subject_company" not in kinds
    assert "missing_rule_reference" not in kinds


def test_analyze_case_plural_rules_legend(tmp_path: Path) -> None:
    text = _SAMPLE_425_TEXT.replace(
        "Pursuant to Rule 425 under the Securities Act of 1933",
        "Pursuant to Rules 165 and 425 under the Securities Act of 1933",
    )
    _write_case(tmp_path, text)

    result = analyze_case(
        tmp_path, {"accession": "0000899140-01-000143", "form": "425"}
    )
    assert result is not None
    fields = result["form_425"]
    assert fields["rule_425"] is True
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_rule_reference" not in kinds


def test_analyze_case_bare_text_flags_missing_fields(tmp_path: Path) -> None:
    _write_case(tmp_path, "A press release with no filing header block.\n")

    result = analyze_case(
        tmp_path, {"accession": "0000006955-22-000018", "form": "425"}
    )
    assert result is not None
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_filer_name" in kinds
    assert "missing_subject_company" in kinds
    assert "missing_rule_reference" in kinds


def test_summarize_cases_scorecard(tmp_path: Path) -> None:
    _write_case(tmp_path, _SAMPLE_425_TEXT)
    first = analyze_case(tmp_path, {"accession": "0000006955-22-000016", "form": "425"})
    assert first is not None
    summary = summarize_cases([first])
    scorecard = summary["form_425_scorecard"]
    assert scorecard["filer_name_count"] == 1
    assert scorecard["subject_company_count"] == 1
    assert scorecard["commission_file_number_count"] == 1
    assert scorecard["rule_425_count"] == 1
    assert scorecard["rule_14a_12_count"] == 1
