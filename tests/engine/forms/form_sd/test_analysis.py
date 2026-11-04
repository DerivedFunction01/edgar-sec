from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.forms.form_sd.analysis import analyze_case, summarize_cases

_COVER_HEAD = """\
UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
FORM SD
SPECIALIZED DISCLOSURE REPORT
ACME WIDGETS CORP.
(Exact name of registrant as specified in its charter)
Delaware
(State or other jurisdiction of incorporation or organization)
001-11288
(Commission File Number)
100 Main Street, Springfield, Illinois 62701
(Address of principal executive offices) (Zip Code)
Jane Doe (217) 555-0100
(Name and telephone number, including area code, of the person to contact in connection with this report)
Check the appropriate box to indicate the rule pursuant to which this form is being filed, and provide the period to which the information in this form applies:
"""

_SAMPLE_CM_TEXT = (
    _COVER_HEAD
    + """\
[X] Rule 13p-1 under the Securities Exchange Act (17 CFR 240.13p-1) for the reporting period from January 1 to December 31, 2024.
[ ] Rule 13q-1 under the Securities Exchange Act (17 CFR 240.13q-1) for the fiscal year ended December 31, 2024.
SECTION 1 - CONFLICT MINERALS DISCLOSURE
Item 1.01 Conflict Minerals Disclosure and Report
Acme has determined that conflict minerals are necessary to the functionality of its products, as more particularly described in the Conflict Minerals Report filed as Exhibit 1.01 to this Form SD.
Item 1.02 Exhibits
The following exhibit is filed as part of this report: Exhibit 1.01 Conflict Minerals Report.
SIGNATURES
Pursuant to the requirements of the Securities Exchange Act of 1934, the registrant has duly caused this report to be signed on its behalf by the undersigned, thereunto duly authorized.
"""
)

_SAMPLE_REP_TEXT = (
    _COVER_HEAD
    + """\
[ ] Rule 13p-1 under the Securities Exchange Act (17 CFR 240.13p-1) for the reporting period from January 1 to December 31, 2024.
[X] Rule 13q-1 under the Securities Exchange Act (17 CFR 240.13q-1) for the fiscal year ended June 30, 2024.
SECTION 1 - CONFLICT MINERALS DISCLOSURE
Item 1.01. Conflict Minerals Disclosure and Report
Not applicable
Item 1.02 Exhibit
Not applicable
SECTION 2 - RESOURCE EXTRACTION ISSUER DISCLOSURE
Item 2.01. Resource Extraction Issuer Disclosure Report
The payment disclosure required by this Form is included as Exhibit 2.01 to this Form SD.
SECTION 3 - EXHIBITS
Item 3.01. Exhibits
The following exhibit is filed as part of this report.
Exhibit Number Description
2.01 Resource Extraction Payment Report
SIGNATURES
Pursuant to the requirements of the Securities Exchange Act of 1934, the registrant has duly caused this report to be signed on its behalf by the undersigned, thereunto duly authorized.
"""
)

_SAMPLE_EXHIBITS_VARIANT_TEXT = (
    _COVER_HEAD
    + """\
[X] Rule 13p-1 under the Securities Exchange Act (17 CFR 240.13p-1) for the reporting period from January 1 to December 31, 2013.
SECTION 1 - CONFLICT MINERALS DISCLOSURE
Item 1.01 Conflict Minerals Disclosure and Report
Acme has determined that conflict minerals are necessary to the functionality of its products.
Item 1.02 Exhibit
The Conflict Minerals Report required by Item 1.01 is filed as Exhibit 1.02 to this Form SD.
SECTION 2 - EXHIBITS
Item 2.01 Exhibits
Exhibit 1.02 - Conflict Minerals Report as required by Items 1.01 and 1.02 of this Form.
SIGNATURES
Pursuant to the requirements of the Securities Exchange Act of 1934, the registrant has duly caused this report to be signed on its behalf by the undersigned, thereunto duly authorized.
"""
)


def _write_case(tmp_path: Path, text: str) -> None:
    ops = tmp_path / "operations"
    ops.mkdir(parents=True)
    (ops / "render_to_txt.txt").write_text(text, encoding="utf-8")


def test_analyze_missing_artifact(tmp_path: Path) -> None:
    result = analyze_case(tmp_path, {"accession": "0000000000-00-000000"})
    assert result is None


def test_analyze_conflict_minerals(tmp_path: Path) -> None:
    _write_case(tmp_path, _SAMPLE_CM_TEXT)
    result = analyze_case(tmp_path, {"accession": "0000006955-24-000016", "form": "SD"})
    assert result is not None
    fields = result["form_sd"]
    assert fields["kind"] == "conflict_minerals"
    assert fields["registrant_name"] == "ACME WIDGETS CORP."
    assert fields["commission_file_number"] == "001-11288"
    assert fields["reporting_period"] == "January 1 to December 31, 2024"
    assert fields["ex_1_01_companion"] is True
    assert fields["ex_2_01_companion"] is False
    assert result["checkmarks"]["rule_13p_1"] is True
    assert result["checkmarks"]["rule_13q_1"] is False
    assert result["taxonomy"]["detected_items"] == ["ITEM 1.01", "ITEM 1.02"]
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "rule_election_unresolved" not in kinds
    assert "missing_registrant_name" not in kinds


def test_analyze_resource_extraction(tmp_path: Path) -> None:
    _write_case(tmp_path, _SAMPLE_REP_TEXT)
    result = analyze_case(tmp_path, {"accession": "0000006955-24-000017", "form": "SD"})
    assert result is not None
    fields = result["form_sd"]
    assert fields["kind"] == "resource_extraction"
    assert fields["reporting_period"] == "June 30, 2024"
    assert fields["ex_2_01_companion"] is True
    assert result["checkmarks"]["rule_13q_1"] is True
    assert result["taxonomy"]["detected_items"] == [
        "ITEM 1.01",
        "ITEM 1.02",
        "ITEM 2.01",
        "ITEM 3.01",
    ]
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_ex_2_01_companion" not in kinds


def test_analyze_exhibits_variant_era(tmp_path: Path) -> None:
    _write_case(tmp_path, _SAMPLE_EXHIBITS_VARIANT_TEXT)
    result = analyze_case(tmp_path, {"accession": "0000006955-14-000018", "form": "SD"})
    assert result is not None
    fields = result["form_sd"]
    assert fields["kind"] == "conflict_minerals"
    assert fields["ex_1_02_companion"] is True
    assert fields["item_2_01_exhibits_variant"] is True


_SAMPLE_TABLE_TEXT = """\
UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
FORM SD
SPECIALIZED DISCLOSURE REPORT
ACME WIDGETS CORP.
<TABLE>
Delaware 001-11288 38-0387840
(State or other jurisdiction of (Commission (IRS Employer
incorporation) File Number) Identification No.)
</TABLE>
100 Main Street, Springfield, Illinois 62701
(Address of principal executive offices) (Zip Code)
Jane Doe (217) 555-0100
(Name and telephone number, including area code, of the person to contact in connection with this report)
Check the appropriate box to indicate the rule pursuant to which this form is being filed, and provide the period to which the information in this form applies:
[X] Rule 13p-1 under the Securities Exchange Act (17 CFR 240.13p-1) for the reporting period from January 1 to December 31, 2024.
SECTION 1 - CONFLICT MINERALS DISCLOSURE
Item 1.01 Conflict Minerals Disclosure and Report
Acme has determined that conflict minerals are necessary to the functionality of its products.
Item 1.02 Exhibits
The following exhibits are filed as part of this report.
<TABLE>
Exhibit No. Description
----------- -----------
1.01 Conflict Minerals Report
</TABLE>
SIGNATURES
Pursuant to the requirements of the Securities Exchange Act of 1934, the registrant has duly caused this report to be signed on its behalf by the undersigned, thereunto duly authorized.
"""


def test_analyze_table_cover_fallbacks(tmp_path: Path) -> None:
    _write_case(tmp_path, _SAMPLE_TABLE_TEXT)
    result = analyze_case(tmp_path, {"accession": "0000006955-24-000019", "form": "SD"})
    assert result is not None
    fields = result["form_sd"]
    assert fields["kind"] == "conflict_minerals"
    assert fields["registrant_name"] == "ACME WIDGETS CORP."
    assert fields["commission_file_number"] == "001-11288"
    assert fields["ex_1_01_companion"] is True
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_registrant_name" not in kinds
    assert "missing_commission_file_number" not in kinds


_SAMPLE_NA_SECTION_TEXT = """\
UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
FORM SD
SPECIALIZED DISCLOSURE REPORT
ACME WIDGETS CORP.
(Exact name of registrant as specified in its charter)
Delaware 001-11288 38-0387840
(State or other jurisdiction of incorporation) (Commission File Number) (IRS Employer Identification No.)
Check the appropriate box to indicate the rule pursuant to which this form is being filed, and provide the period to which the information in this form applies:
Rule 13p-1 under the Securities Exchange Act (17 CFR 240.13p-1) for the reporting period from January 1 to December 31, 2024.
Rule 13q-1 under the Securities Exchange Act (17 CFR 240.13q-1) for the fiscal year ended December 31, 2024.
SECTION 1 - CONFLICT MINERALS DISCLOSURE
Item 1.01 Conflict Minerals Disclosure and Report
Acme has determined that conflict minerals are necessary to the functionality of its products.
Item 1.02 Exhibits
The Conflict Minerals Report described in Item 1.01 is filed as Exhibit 1.01 to this Form SD.
SECTION 2 - RESOURCE EXTRACTION ISSUER DISCLOSURE
Item 2.01 Resource Extraction Issuer Disclosure and Report
Not applicable.
SIGNATURES
Pursuant to the requirements of the Securities Exchange Act of 1934, the registrant has duly caused this report to be signed on its behalf by the undersigned, thereunto duly authorized.
"""


def test_analyze_not_applicable_section_is_not_kind_evidence(
    tmp_path: Path,
) -> None:
    _write_case(tmp_path, _SAMPLE_NA_SECTION_TEXT)
    result = analyze_case(tmp_path, {"accession": "0000006955-24-000020", "form": "SD"})
    assert result is not None
    fields = result["form_sd"]
    assert fields["kind"] == "conflict_minerals"
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_ex_2_01_companion" not in kinds


_SAMPLE_99_1_TEXT = """\
UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
FORM SD
SPECIALIZED DISCLOSURE REPORT
ACME ENERGY CORP.
(Exact name of registrant as specified in its charter)
Texas 001-33445 47-0472895
(State or other jurisdiction of incorporation) (Commission File Number) (IRS Employer Identification No.)
Check the appropriate box to indicate the rule pursuant to which this form is being filed, and provide the period to which the information in this form applies:
[ ] Rule 13p-1 under the Securities Exchange Act (17 CFR 240.13p-1) for the reporting period from January 1 to December 31, 2024.
[X] Rule 13q-1 under the Securities Exchange Act (17 CFR 240.13q-1) for the fiscal year ended December 31, 2024.
SECTION 2 - RESOURCE EXTRACTION ISSUER DISCLOSURE
Item 2.01 Resource Extraction Issuer Disclosure and Report
The payment disclosure required by this Form is included as Exhibit 99.1 to this Form SD.
SIGNATURES
Pursuant to the requirements of the Securities Exchange Act of 1934, the registrant has duly caused this report to be signed on its behalf by the undersigned, thereunto duly authorized.
"""


def test_analyze_rep_exhibit_99_1_variant(tmp_path: Path) -> None:
    _write_case(tmp_path, _SAMPLE_99_1_TEXT)
    result = analyze_case(tmp_path, {"accession": "0000006955-24-000021", "form": "SD"})
    assert result is not None
    fields = result["form_sd"]
    assert fields["kind"] == "resource_extraction"
    assert fields["ex_2_01_companion"] is False
    assert fields["ex_99_1_companion"] is True
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_ex_2_01_companion" not in kinds


def test_summarize_counts_kinds(tmp_path: Path) -> None:
    _write_case(tmp_path, _SAMPLE_CM_TEXT)
    rep = analyze_case(tmp_path, {"accession": "0000006955-24-000016", "form": "SD"})
    assert rep is not None
    summary = summarize_cases([rep])
    scorecard = summary["form_sd_scorecard"]
    assert scorecard["kind_counts"] == {"conflict_minerals": 1}
    assert scorecard["rule_checked_counts"]["rule_13p_1"] == 1
    assert scorecard["cmr_companion_count"] == 1
