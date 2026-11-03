from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.forms.form_fwp.analysis import analyze_case, summarize_cases

_SAMPLE_FWP_TEXT = """\
Acme Financial Company LLC

Guarantor:
Acme Holdings Inc.

Free Writing Prospectus
Filed Pursuant to Rule 433
Registration Statement Nos. 333-275079 and 333-275079-04
Supplementing the Prospectus Dated May 10, 2024

SUMMARY TERMS

Issuer: Acme Financial Company LLC
CUSIP: 48134WZA8

The notes are medium-term notes issued by the Issuer.

Tax Considerations

Certain U.S. federal income tax considerations apply to holders of the
notes.
"""


def _write_case(tmp_path: Path, text: str) -> None:
    ops = tmp_path / "operations"
    ops.mkdir(parents=True)
    (ops / "render_to_txt.txt").write_text(text, encoding="utf-8")


def test_analyze_case_missing_artifact(tmp_path: Path) -> None:
    result = analyze_case(tmp_path, {"accession": "0000000000-00-000000"})
    assert result is None


def test_analyze_case_fwp_header(tmp_path: Path) -> None:
    _write_case(tmp_path, _SAMPLE_FWP_TEXT)

    result = analyze_case(
        tmp_path, {"accession": "0000006955-22-000016", "form": "FWP"}
    )
    assert result is not None
    assert result["family"] == "FWP"
    fields = result["form_fwp"]
    assert fields["issuer_name"] == "Acme Financial Company LLC"
    assert fields["guarantor_name"] == "Acme Holdings Inc."
    assert fields["rule_reference"] == "433"
    assert fields["registration_numbers"] == ["333-275079", "333-275079-04"]
    assert fields["cusip"] == "48134WZA8"
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_issuer_name" not in kinds
    assert "missing_rule_reference" not in kinds
    assert "missing_registration_number" not in kinds


def test_analyze_case_bare_text_flags_missing_fields(tmp_path: Path) -> None:
    _write_case(tmp_path, "A short communication with no header block.\n")

    result = analyze_case(
        tmp_path, {"accession": "0000006955-22-000018", "form": "FWP"}
    )
    assert result is not None
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_rule_reference" in kinds
    assert "missing_registration_number" in kinds


def test_summarize_cases_scorecard(tmp_path: Path) -> None:
    _write_case(tmp_path, _SAMPLE_FWP_TEXT)
    first = analyze_case(tmp_path, {"accession": "0000006955-22-000016", "form": "FWP"})
    assert first is not None
    summary = summarize_cases([first])
    scorecard = summary["form_fwp_scorecard"]
    assert scorecard["issuer_name_count"] == 1
    assert scorecard["guarantor_name_count"] == 1
    assert scorecard["rule_reference_count"] == 1
    assert scorecard["registration_number_count"] == 1
    assert scorecard["cusip_count"] == 1
