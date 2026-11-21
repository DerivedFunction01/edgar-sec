from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.forms.form_15.analysis import analyze_case, summarize_cases

_SAMPLE_15_TEXT = """\
UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
FORM 15
CERTIFICATION AND NOTICE OF TERMINATION OF REGISTRATION UNDER SECTION 12(g) OF THE SECURITIES EXCHANGE ACT OF 1934 OR SUSPENSION OF DUTY TO FILE REPORTS UNDER SECTIONS 13 AND 15(d) OF THE SECURITIES EXCHANGE ACT OF 1934.
Commission File Number: 1-11288
ACME WIDGETS CORP.
(Exact name of registrant as specified in its charter)
100 Main Street
Springfield, Illinois 62701
(217) 555-0100
(Address, including zip code, and telephone number, including area code, of registrant's principal executive offices)
Common Stock, par value $0.01 per share
(Title of each class of securities covered by this Form)
None
(Titles of all other classes of securities for which a duty to file reports under Section 13(a) or 15(d) remains)
Please place an X in the box(es) to designate the appropriate rule provision(s) relied upon to terminate or suspend the duty to file reports:
Rule 12g-4(a)(1) [ ]
Rule 12g-4(a)(2) [ ]
Rule 12h-3(b)(1)(i) [X]
Rule 12h-3(b)(1)(ii) [ ]
Rule 15d-6 [ ]
Approximate number of holders of record as of the certification or notice date: 42
Pursuant to the requirements of the Securities Exchange Act of 1934, Acme Widgets Corp. has caused this certification/notice to be signed on its behalf by the undersigned duly authorized person.
Date: April 29, 2022
By: /s/ Jane Doe
Jane Doe
Chief Financial Officer
"""


def _write_case(tmp_path: Path, text: str) -> None:
    ops = tmp_path / "operations"
    ops.mkdir(parents=True)
    (ops / "render_to_txt.txt").write_text(text, encoding="utf-8")


def test_analyze_case_missing_artifact(tmp_path: Path) -> None:
    result = analyze_case(tmp_path, {"accession": "0000000000-00-000000"})
    assert result is None


def test_analyze_case_valid_synthetic(tmp_path: Path) -> None:
    _write_case(tmp_path, _SAMPLE_15_TEXT)

    result = analyze_case(
        tmp_path, {"accession": "0000006955-22-000016", "form": "15-12B"}
    )
    assert result is not None
    assert result["family"] == "15"
    fields = result["form_15"]
    assert fields["commission_file_number"] == "1-11288"
    assert fields["registrant_name"] == "ACME WIDGETS CORP."
    assert fields["holder_value"] == "42"
    assert fields["signature"]["present"] is True
    assert fields["signature"]["conformed"] is True
    assert result["checkmarks"]["rule_12h3_b1_i"] is True
    assert result["checkmarks"]["rule_12g4_a1"] is False
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_commission_file_number" not in kinds
    assert "missing_registrant_name" not in kinds
    assert "missing_holder_count" not in kinds
    assert "missing_signature" not in kinds
    assert "no_rule_provision_checked" not in kinds


_EARLY_ERA_15_TEXT = """\
SECURITIES AND EXCHANGE COMMISSION
FORM 15
Certification and Notice of Termination of Registration under Section 12(g) of the Securities Exchange Act of 1934
Commission File No.  1-6880
-----------
First Bank System, Inc.
-----------------------------------------------------------
(Exact name of registrant as specified in its charter)
First Bank Place, Minneapolis, Minnesota 55402
(Address, including zip code, and telephone number, including area code of registrant's principal executive offices)
Common Stock
(Title of each class of securities covered by this Form)
None
(Titles of all other classes of securities for which a duty to file reports under Section 13(a) or 15(d) remains)
Please place and [X] in the box(es) to designate the appropriate rule provision(s) relied upon to terminate or suspend the duty to file reports:
Rule 12g-4(a)(1)(i)   [X]          Rule 12h-3(b)(1)(ii)  [ ]
Rule 12h-3(b)(1)(i)   [X]
Approximate number of holders of record as of the certification or notice date:  One
Pursuant to the requirements of the Securities Exchange Act of 1934, First Bank System, Inc. has caused this certificate/notice to be signed on its behalf by the undersigned duly authorized person.
DATE:  March 31, 1997                        BY:  /s/ Lee R. Mitau
Lee R. Mitau
"""


def test_analyze_case_early_era_layout_variants(tmp_path: Path) -> None:
    _write_case(tmp_path, _EARLY_ERA_15_TEXT)

    result = analyze_case(
        tmp_path, {"accession": "0000912057-97-011588", "form": "15-12B"}
    )
    assert result is not None
    fields = result["form_15"]
    assert fields["commission_file_number"] == "1-6880"
    assert fields["registrant_name"] == "First Bank System, Inc."
    assert fields["holder_value"] == "one"
    assert fields["signature"]["present"] is True
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_commission_file_number" not in kinds
    assert "missing_registrant_name" not in kinds
    assert "missing_holder_count" not in kinds
    assert "missing_signature" not in kinds


def test_analyze_case_file_number_value_above_caption(tmp_path: Path) -> None:
    above = tmp_path / "above"
    _write_case(
        above,
        "UNITED STATES\nSECURITIES AND EXCHANGE COMMISSION\nFORM 15/A\n"
        "CERTIFICATION AND NOTICE OF TERMINATION OF REGISTRATION\n"
        "333-152242\n(Commission File Number)\nYinfu Example Corporation\n"
        "(Exact name of registrant as specified in its charter)\n",
    )
    result = analyze_case(above, {"accession": "0001493152-13-001768"})
    assert result is not None
    assert result["form_15"]["commission_file_number"] == "333-152242"

    plural = tmp_path / "plural"
    _write_case(
        plural,
        "UNITED STATES\nSECURITIES AND EXCHANGE COMMISSION\nFORM 15\n"
        "CERTIFICATION AND NOTICE OF TERMINATION OF REGISTRATION\n"
        "Commission File Numbers:  2-95495\n33-2502\n"
        "Example Corporation\n"
        "(Exact name of registrant as specified in its charter)\n",
    )
    result = analyze_case(plural, {"accession": "0000006281-16-000053"})
    assert result is not None
    assert result["form_15"]["commission_file_number"] == "2-95495"


def test_analyze_case_bare_cover_reports_missing_fields(tmp_path: Path) -> None:
    _write_case(
        tmp_path,
        "UNITED STATES\nSECURITIES AND EXCHANGE COMMISSION\nFORM 15\n"
        "CERTIFICATION AND NOTICE OF TERMINATION OF REGISTRATION\n",
    )

    result = analyze_case(tmp_path, {"accession": "0000000000-00-000001"})
    assert result is not None
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_commission_file_number" in kinds
    assert "missing_registrant_name" in kinds
    assert "missing_holder_count" in kinds
    assert "missing_signature" in kinds
    assert "no_rule_provision_checked" in kinds


def test_summarize_cases_empty() -> None:
    summary = summarize_cases([])
    assert summary["case_count"] == 0
    assert summary["family"] == "15"


def test_summarize_cases_scorecard(tmp_path: Path) -> None:
    _write_case(tmp_path, _SAMPLE_15_TEXT)
    rep = analyze_case(
        tmp_path, {"accession": "0000006955-22-000016", "form": "15-12B"}
    )
    assert rep is not None
    summary = summarize_cases([rep])
    assert summary["family"] == "15"
    scorecard = summary["form_15_scorecard"]
    assert scorecard["commission_file_number_count"] == 1
    assert scorecard["registrant_name_count"] == 1
    assert scorecard["holder_value_count"] == 1
    assert scorecard["signature_conformed_count"] == 1
    assert scorecard["rule_checked_counts"]["rule_12h3_b1_i"] == 1
    assert scorecard["cases_with_any_rule"] == 1
