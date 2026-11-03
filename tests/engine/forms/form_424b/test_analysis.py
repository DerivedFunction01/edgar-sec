from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.forms.form_424b.analysis import analyze_case, summarize_cases

_SAMPLE_424B3_TEXT = """\
Filed Pursuant to Rule 424(b)(3)
Registration No. 333-287762

PROSPECTUS

39,705,883 Shares

Common Stock

This prospectus relates to the offer and sale from time to time of up to
39,705,883 shares of common stock, par value $0.001 per share, of Acme
Widgets Corporation (the "Company") by the selling stockholders named
herein.

PROSPECTUS SUMMARY

The Company is a designer and manufacturer of widgets.

RISK FACTORS

Investing in our common stock involves a high degree of risk.

USE OF PROCEEDS

We will not receive any proceeds from the sale of shares by the selling
stockholders.

PLAN OF DISTRIBUTION

The selling stockholders may sell their shares in ordinary brokerage
transactions.
"""

_SAMPLE_424B2_TEXT = """\
PRICING SUPPLEMENT
(TO PROSPECTUS SUPPLEMENT AND PROSPECTUS EACH DATED MARCH 9, 2023)
Filed Pursuant to Rule 424(b)(2)
Registration Statement No. 333-270200

The Toronto-Dominion Bank

$5,000,000

Senior Medium-Term Notes, Series D

CUSIP / ISIN: 89114QKV9 / US89114QKV90

PROSPECTUS SUMMARY

This pricing supplement relates to an offering of senior medium-term
notes by the Bank.

RISK FACTORS

An investment in the notes entails significant risks.
"""


def _write_case(tmp_path: Path, text: str) -> None:
    ops = tmp_path / "operations"
    ops.mkdir(parents=True)
    (ops / "render_to_txt.txt").write_text(text, encoding="utf-8")


def test_analyze_case_missing_artifact(tmp_path: Path) -> None:
    result = analyze_case(tmp_path, {"accession": "0000000000-00-000000"})
    assert result is None


def test_analyze_case_prospectus_cover(tmp_path: Path) -> None:
    _write_case(tmp_path, _SAMPLE_424B3_TEXT)

    result = analyze_case(
        tmp_path, {"accession": "0000006955-22-000016", "form": "424B3"}
    )
    assert result is not None
    assert result["family"] == "424B"
    fields = result["form_424b"]
    assert fields["rule_reference"] == "424(b)(3)"
    assert fields["registration_number"] == "333-287762"
    assert fields["document_kind"] == "prospectus"
    assert fields["registrant_name"] == "Acme Widgets Corporation"
    assert fields["share_count"] == "39,705,883"
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_rule_reference" not in kinds
    assert "missing_registration_number" not in kinds
    assert "missing_registrant_name" not in kinds
    assert "missing_document_kind" not in kinds


def test_analyze_case_pricing_supplement_cover(tmp_path: Path) -> None:
    _write_case(tmp_path, _SAMPLE_424B2_TEXT)

    result = analyze_case(
        tmp_path, {"accession": "0000006955-22-000017", "form": "424B2"}
    )
    assert result is not None
    fields = result["form_424b"]
    assert fields["rule_reference"] == "424(b)(2)"
    assert fields["registration_number"] == "333-270200"
    assert fields["document_kind"] == "pricing_supplement"
    assert fields["offering_amount"] == "5,000,000"
    assert fields["cusip"] == "89114QKV9"


def test_analyze_case_legacy_caption_variants(tmp_path: Path) -> None:
    _write_case(
        tmp_path,
        "Filed pursuant to Rule No. 424(b)(3)\n"
        "File Number 333-74464\n\n"
        "PROSPECTUS SUPPLEMENT NO. 2\n"
        "REGENERON PHARMACEUTICALS, INC.\n",
    )

    result = analyze_case(
        tmp_path, {"accession": "0000950123-02-001029", "form": "424B3"}
    )
    assert result is not None
    fields = result["form_424b"]
    assert fields["rule_reference"] == "424(b)(3)"
    assert fields["registration_number"] == "333-74464"


def test_analyze_case_bare_text_flags_missing_fields(tmp_path: Path) -> None:
    _write_case(tmp_path, "Some body text without any offering header.\n")

    result = analyze_case(
        tmp_path, {"accession": "0000006955-22-000018", "form": "424B5"}
    )
    assert result is not None
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_rule_reference" in kinds
    assert "missing_registration_number" in kinds
    assert "missing_document_kind" in kinds


def test_summarize_cases_scorecard(tmp_path: Path) -> None:
    _write_case(tmp_path, _SAMPLE_424B3_TEXT)
    first = analyze_case(
        tmp_path, {"accession": "0000006955-22-000016", "form": "424B3"}
    )
    assert first is not None
    summary = summarize_cases([first])
    scorecard = summary["form_424b_scorecard"]
    assert scorecard["rule_reference_count"] == 1
    assert scorecard["registration_number_count"] == 1
    assert scorecard["registrant_name_count"] == 1
    assert scorecard["document_kind_counts"] == {"prospectus": 1}
    assert scorecard["rule_reference_counts"] == {"424(b)(3)": 1}
