from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.forms.form_abs_reports.analysis import (
    analyze_case,
    summarize_cases,
)

_SAMPLE_10D_TEXT = """\
UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
FORM 10-D
ASSET-BACKED ISSUER DISTRIBUTION REPORT PURSUANT TO SECTION 13 OR 15(d) OF THE SECURITIES EXCHANGE ACT OF 1934
For the monthly distribution period from August 1, 2026 to August 31, 2026
Commission File Number of issuing entity: 001-32822
Central Index Key Number of issuing entity: 0001353226
ACME TRUST SERIES 2026-1
(Exact name of issuing entity as specified in its charter)
Commission File Number of depositor: 001-31818
Central Index Key Number of depositor: 0001140396
ACME FIXED-INCOME SECURITIES, INC.
(Exact name of depositor and sponsor as specified in its charter)
New York
(State or other jurisdiction of incorporation or organization of the issuing entity)
Indicate by check mark whether the registrant (1) has filed all reports required to be filed by Section 13 or 15(d) of the Securities Exchange Act of 1934 during the preceding 12 months, and (2) has been subject to such filing requirements for the past 90 days.
Yes [X] No [ ]
PART I - DISTRIBUTION INFORMATION
Item 1. Distribution and Pool Performance Information.
A distribution was made to holders of the certificates.
Item 1A. Asset-Level Information.
None.
PART II - OTHER INFORMATION
Item 2. Legal Proceedings.
None.
Item 10. Exhibits.
Exhibit 99.1 Trustee's Distribution Statement.
SIGNATURES
Pursuant to the requirements of the Securities Exchange Act of 1934, the registrant has duly caused this report to be signed.
"""

_SAMPLE_15G_TEXT = """\
UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
FORM ABS-15G
ASSET-BACKED SECURITIZER REPORT PURSUANT TO SECTION 15G OF THE SECURITIES EXCHANGE ACT OF 1934
Check the appropriate box to indicate the filing obligation to which this form is intended to satisfy:
[X] Rule 15Ga-1 under the Exchange Act (17 CFR 240.15Ga-1) for the reporting period January 1, 2011 to December 31, 2011
[ ] Rule 15Ga-2 under the Exchange Act (17 CFR 240.15Ga-2).
Date of Report (Date of earliest event reported): February 8, 2012
Commission File Number of securitizer: 025-14602
Central Index Key Number of securitizer: 0000310522
ACME MORTGAGE CORPORATION
(Exact name of securitizer as specified in its charter)
Indicate by check mark whether the securitizer has no activity to report for the initial period pursuant to Rule 15Ga-1(c)(1): [ ]
Indicate by check mark whether the securitizer has no activity to report for the quarterly period pursuant to Rule 15Ga-1(c)(2)(i): [ ]
Indicate by check mark whether the securitizer has no activity to report for the annual period pursuant to Rule 15Ga-1(c)(2)(ii): [ ]
INFORMATION TO BE INCLUDED IN THE REPORT
PART I: REPRESENTATION AND WARRANTY INFORMATION
Name of Issuing Entity Name of Originator Total Assets by Originator
ACME TRUST 2026-1 ACME ORIGINATOR LLC 10 $1,000,000
PART II: FINDINGS AND CONCLUSIONS OF THIRD-PARTY DUE DILIGENCE REPORTS
Item 2.01 Findings and Conclusions of a Third Party Due Diligence Report Obtained by the Issuer
See the report attached as Exhibit 99.1.
SIGNATURES
Pursuant to the requirements of the Securities Exchange Act of 1934, the reporting entity has duly caused this report to be signed.
"""

_SAMPLE_15G_ABOVE_CAPTION_TEXT = """\
UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
FORM ABS-15G
ASSET-BACKED SECURITIZER REPORT PURSUANT TO SECTION 15G OF THE SECURITIES EXCHANGE ACT OF 1934
Check the appropriate box to indicate the filing obligation to which this form is intended to satisfy:
[X] Rule 15Ga-1 under the Exchange Act (17 CFR 240.15Ga-1) for the reporting period from January 1, 2026 to March 31, 2026
Date of Report (Date of earliest event reported): May 17, 2026
ACME BANK PLC
(Exact name of securitizer as specified in its charter)
1-99999 1234567

-------------------------------------------------
(Commission File Number of Securitizer) (Central Index Key Number of Securitizer)
Indicate by check mark whether the securitizer has no activity to report for the initial period pursuant to Rule 15Ga-1(c)(1): [X]
Indicate by check mark whether the securitizer has no activity to report for the quarterly period pursuant to Rule 15Ga-1(c)(2)(i): [X]
Indicate by check mark whether the securitizer has no activity to report for the annual period pursuant to Rule 15Ga-1(c)(2)(ii): [ ]
Item 1.02 Periodic Filing of Rule 15Ga-1 Representations and Warranties Disclosure
No Activity to Report.
SIGNATURES
Pursuant to the requirements of the Securities Exchange Act of 1934, the reporting entity has duly caused this report to be signed.
"""

_SAMPLE_15G_BEFORE_CAPTION_TEXT = """\
UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
FORM ABS-15G
ASSET-BACKED SECURITIZER REPORT PURSUANT TO SECTION 15G OF THE SECURITIES EXCHANGE ACT OF 1934
Check the appropriate box to indicate the filing obligation to which this form is intended to satisfy:
[X] Rule 15Ga-1 under the Exchange Act (17 CFR 240.15Ga-1) for the reporting period January 1, 2015 to December 31, 2015
Date of Report (Date of earliest event reported):
February 12. 2016
Credit Acceptance Corporation
(Exact name of securitizer as specified in its charter)
<TABLE>
000-20202 (Commission File Number of securitizer)  0000885550 (Central Index Key Number of securitizer)
</TABLE>
Indicate by check mark whether the securitizer has no activity to report for the initial period pursuant to Rule 15Ga-1(c)(1) [ ]
Indicate by check mark whether the securitizer has no activity to report for the quarterly period pursuant to Rule 15Ga-1(c)(2)(i) [ ]
Indicate by check mark whether the securitizer has no activity to report for the annual period pursuant to Rule 15Ga-1(c)(2)(ii) [X]
SIGNATURES
Pursuant to the requirements of the Securities Exchange Act of 1934, the reporting entity has duly caused this report to be signed.
"""

_SAMPLE_15G_WRAPPED_CAPTION_TEXT = """\
UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
FORM ABS-15G
ASSET-BACKED SECURITIZER REPORT PURSUANT TO SECTION 15G OF THE SECURITIES EXCHANGE ACT OF 1934
Check the appropriate box to indicate the filing obligation to which this form is intended to satisfy:
[X]  Rule 15Ga-1 under the Exchange Act (17 CFR 240.15Ga-1) for the reporting period January 1, 2013 to December 31, 2013
Date of Report (Date of earliest event reported): February 7, 2014
FEDERAL AGRICULTURAL MORTGAGE CORPORATION
(Exact Name of Securitizer as Specified in Charter)
<TABLE>
Federally chartered instrumentality of the United States        001-14951               0000845877
     (State or Other Jurisdiction of Incorporation)          (Commission File       (Central Index Key
                                                          Number of Securitizer)  Number of Securitizer)
</TABLE>
Indicate by check mark whether the securitizer has no activity to report for the initial period pursuant to Rule 15Ga-1(c)(1) [ ]
Indicate by check mark whether the securitizer has no activity to report for the quarterly period pursuant to Rule 15Ga-1(c)(2)(i) [ ]
Indicate by check mark whether the securitizer has no activity to report for the annual period pursuant to Rule 15Ga-1(c)(2)(ii) [X]
SIGNATURES
Pursuant to the requirements of the Securities Exchange Act of 1934, the registrant has duly caused this report to be signed.
"""

_SAMPLE_15G_BLANK_TEMPLATE_TEXT = """\
UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
FORM ABS-15G
Asset-Backed Securitizer Report Pursuant to Section 15G of The Securities Exchange Act of 1934
Check the appropriate box to indicate the filing obligation to which this form is intended to satisfy:
[ ] Rule 15Ga-1 under the Exchange Act (17 CFR 240.15Ga-1) for the reporting period: ________ to _________.
Date of Report (Date of earliest event reported): _________
Commission File Number of securitizer: _________
Central Index Key Number of securitizer: _________
[X] Rule 15Ga-2 under the Exchange Act (17 CFR 240.15Ga-2).
ACME CORPORATION
(Exact name of securitizer as specified in its charter)
Item 2.01 Findings and Conclusions of a Third Party Due Diligence Report Obtained by the Issuer
Attached as Exhibit 99.1 is a due diligence report.
SIGNATURES
Pursuant to the requirements of the Securities Exchange Act of 1934, the reporting entity has duly caused this report to be signed.
"""

_SAMPLE_15G_FRAGMENT = """\
File 02 of 12
Name of Issuing Entity Check if Registered Name of Originator Total Assets by Originator Assets that Were Subject of Demand
31418DHM7 ACME MORTGAGE CO. 1 $271,200.00 0 $0.00
ACME TRUST 2026-1 ACME ORIGINATOR LLC 2 $618,441.00 0 $0.00
"""


def _write_case(tmp_path: Path, text: str) -> None:
    ops = tmp_path / "operations"
    ops.mkdir(parents=True)
    (ops / "render_to_txt.txt").write_text(text, encoding="utf-8")


def test_analyze_missing_artifact(tmp_path: Path) -> None:
    result = analyze_case(tmp_path, {"accession": "0000000000-00-000000"})
    assert result is None


def test_analyze_10d_distribution(tmp_path: Path) -> None:
    _write_case(tmp_path, _SAMPLE_10D_TEXT)
    result = analyze_case(
        tmp_path, {"accession": "0001353226-26-000001", "form": "10-D"}
    )
    assert result is not None
    fields = result["form_abs_reports"]
    assert fields["kind"] == "distribution"
    assert fields["issuing_entity_file_number"] == "001-32822"
    assert fields["issuing_entity_cik"] == "0001353226"
    assert fields["depositor_file_number"] == "001-31818"
    assert fields["depositor_cik"] == "0001140396"
    assert fields["issuing_entity_name"] == "ACME TRUST SERIES 2026-1"
    assert fields["distribution_period"] == {
        "from": "August 1, 2026",
        "to": "August 31, 2026",
    }
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_issuing_entity_file_number" not in kinds
    assert "missing_distribution_period" not in kinds
    assert "no_items_detected" not in kinds


def test_analyze_10d_period_table_wrapped(tmp_path: Path) -> None:
    text = _SAMPLE_10D_TEXT.replace(
        "For the monthly distribution period from August 1, 2026 to August 31, 2026",
        "For the monthly distribution period from\n<TABLE>\n"
        "August 1, 2026  to  August 31, 2026\n</TABLE>",
    )
    _write_case(tmp_path, text)
    result = analyze_case(
        tmp_path, {"accession": "0001357660-26-000001", "form": "10-D"}
    )
    assert result is not None
    assert result["form_abs_reports"]["distribution_period"] == {
        "from": "August 1, 2026",
        "to": "August 31, 2026",
    }


def test_analyze_10d_period_loose_punctuation(tmp_path: Path) -> None:
    text = _SAMPLE_10D_TEXT.replace(
        "from August 1, 2026 to August 31, 2026",
        "from August1, 2026 to, August 31 , 2026",
    )
    _write_case(tmp_path, text)
    result = analyze_case(
        tmp_path, {"accession": "0000905148-07-000001", "form": "10-D"}
    )
    assert result is not None
    assert result["form_abs_reports"]["distribution_period"] == {
        "from": "August 1, 2026",
        "to": "August 31, 2026",
    }


def test_analyze_abs_15g_face(tmp_path: Path) -> None:
    _write_case(tmp_path, _SAMPLE_15G_TEXT)
    result = analyze_case(
        tmp_path, {"accession": "0000310522-12-000003", "form": "ABS-15G"}
    )
    assert result is not None
    fields = result["form_abs_reports"]
    assert fields["kind"] == "securitizer"
    assert fields["shape"] == "face"
    assert fields["securitizer_file_number"] == "025-14602"
    assert fields["securitizer_cik"] == "0000310522"
    assert fields["date_of_report"] == "February 8, 2012"
    assert fields["reporting_period"] == {
        "from": "January 1, 2011",
        "to": "December 31, 2011",
    }
    assert fields["table_header_present"] is True
    assert result["checkmarks"]["rule_15ga_1"] is True
    assert result["checkmarks"]["rule_15ga_2"] is False
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "no_obligation_checked" not in kinds
    assert "missing_securitizer_cik" not in kinds


def test_analyze_abs_15g_above_caption_pair(tmp_path: Path) -> None:
    _write_case(tmp_path, _SAMPLE_15G_ABOVE_CAPTION_TEXT)
    result = analyze_case(
        tmp_path, {"accession": "0001234567-26-000001", "form": "ABS-15G"}
    )
    assert result is not None
    fields = result["form_abs_reports"]
    assert fields["shape"] == "face"
    assert fields["securitizer_file_number"] == "1-99999"
    assert fields["securitizer_cik"] == "0001234567"
    assert fields["date_of_report"] == "May 17, 2026"
    assert "ITEM 1.02" in result["taxonomy"]["detected_items"]
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_securitizer_file_number" not in kinds
    assert "missing_securitizer_cik" not in kinds
    assert "no_items_detected" not in kinds


def test_analyze_abs_15g_value_before_caption(tmp_path: Path) -> None:
    # Specimen-derived (Credit Acceptance faces): values precede their
    # parenthetical captions on one rendered line inside the face table.
    _write_case(tmp_path, _SAMPLE_15G_BEFORE_CAPTION_TEXT)
    result = analyze_case(
        tmp_path, {"accession": "0000885550-16-000084", "form": "ABS-15G"}
    )
    assert result is not None
    fields = result["form_abs_reports"]
    assert fields["shape"] == "face"
    assert fields["securitizer_file_number"] == "000-20202"
    assert fields["securitizer_cik"] == "0000885550"
    assert fields["date_of_report"] == "February 12, 2016"
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_securitizer_file_number" not in kinds
    assert "missing_securitizer_cik" not in kinds


def test_analyze_abs_15g_wrapped_caption_pair(tmp_path: Path) -> None:
    # Specimen-derived (Farmer Mac face): the three-column face table wraps
    # its captions across lines, interleaving the two caption completions.
    _write_case(tmp_path, _SAMPLE_15G_WRAPPED_CAPTION_TEXT)
    result = analyze_case(
        tmp_path, {"accession": "0000845877-14-000016", "form": "ABS-15G"}
    )
    assert result is not None
    fields = result["form_abs_reports"]
    assert fields["shape"] == "face"
    assert fields["securitizer_file_number"] == "001-14951"
    assert fields["securitizer_cik"] == "0000845877"
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_securitizer_file_number" not in kinds
    assert "missing_securitizer_cik" not in kinds


def test_analyze_abs_15g_blank_template_stays_absent(tmp_path: Path) -> None:
    # Specimen-derived (15Ga-2 template faces): identity fields are
    # underscores as filed, so absence is the filed fact, not a miss.
    _write_case(tmp_path, _SAMPLE_15G_BLANK_TEMPLATE_TEXT)
    result = analyze_case(
        tmp_path, {"accession": "0000885550-16-000139", "form": "ABS-15G"}
    )
    assert result is not None
    fields = result["form_abs_reports"]
    assert fields["shape"] == "face"
    assert fields["securitizer_file_number"] is None
    assert fields["securitizer_cik"] is None
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_securitizer_file_number" in kinds
    assert "no_obligation_checked" not in kinds


def test_analyze_abs_15g_table_fragment(tmp_path: Path) -> None:
    _write_case(tmp_path, _SAMPLE_15G_FRAGMENT)
    result = analyze_case(
        tmp_path, {"accession": "0000310522-26-000067", "form": "ABS-15G/A"}
    )
    assert result is not None
    fields = result["form_abs_reports"]
    assert fields["kind"] == "securitizer"
    assert fields["shape"] == "table_fragment"
    assert fields["part_caption"] == {"index": 2, "count": 12}
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_securitizer_file_number" not in kinds
    assert "no_obligation_checked" not in kinds


def _rep_shell() -> dict:
    return {
        "boundary": {"method": "structural", "confidence": 1.0},
        "cover_lines": 40,
        "checkmarks": {},
        "corridor": {},
        "taxonomy": {"item_count": 0, "detected_items": []},
        "notes": {"note_count": 0},
        "anomalies": [],
    }


_SAMPLE_15G_MANGLED_FRAGMENT = """\
File 51 of 54
Nam Che Nam Total Assets by Assets that Were Subject of Demand
of k i of Originator
ssu Reg rig
313 ACME FIFTH THIRD MORTGAGE COMPANY 5 $1,514,370.00 0 $0.00
"""


# Specimen-derived (accession 0000310522-12-000003): the face rides in
# small tagged tables and the body is one giant table.
_GIANT_TABLE_ROWS = "\n".join(
    f"3130AH{i} ACME ORIGINATOR {i} $1,000.00 0 $0.00" for i in range(520)
)
_SAMPLE_15G_GIANT_TABLE_FACE = (
    """\
UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
FORM ABS-15G
ASSET-BACKED SECURITIZER
REPORT PURSUANT TO SECTION 15G OF
THE SECURITIES EXCHANGE ACT OF 1934
Check the appropriate box to indicate the filing obligation to which this form is intended to satisfy:
<TABLE>
[X]  Rule 15Ga-1 under the Exchange Act (17 CFR 240.15Ga-1) for the reporting period January 1, 2009 to December 31, 2011
[ ]  Rule 15Ga-2 under the Exchange Act (17 CFR 240.15Ga-2).
</TABLE>
Date of Report (Date of earliest event reported): February 8, 2012
<TABLE>
       025-14602                 0000310522
-------------------------------------------------
(Commission File Number)  (Central Index Key No.)
</TABLE>
Indicate by check mark whether the securitizer has no activity to report for the initial period pursuant to Rule 15Ga-1(c)(1): [ ]
Indicate by check mark whether the securitizer has no activity to report for the quarterly period pursuant to Rule 15Ga-1(c)(2)(i): [ ]
<TABLE>
"""
    + _GIANT_TABLE_ROWS
    + "\n</TABLE>\n"
)

# Specimen-derived (accession 0000310522-12-000101): the part caption
# survives only in the filename banner; the table headers are wrapped.
_SAMPLE_15G_BANNER_FRAGMENT = """\
ABS-15G/A
1
15GaFile_09_of_42_0107_0201.htm
15GAFILE_09_OF_42_0107_0201
ABS-15G
Name of
Originator
Total
Assets by Originator
31418DHM7 ACME MORTGAGE CO. 1 $271,200.00 0 $0.00
"""


def test_analyze_abs_15g_giant_table_face(tmp_path: Path) -> None:
    _write_case(tmp_path, _SAMPLE_15G_GIANT_TABLE_FACE)
    result = analyze_case(
        tmp_path, {"accession": "0000310522-12-000003", "form": "ABS-15G"}
    )
    assert result is not None
    fields = result["form_abs_reports"]
    assert fields["shape"] == "face"
    assert fields["securitizer_file_number"] == "025-14602"
    assert fields["securitizer_cik"] == "0000310522"
    assert fields["date_of_report"] == "February 8, 2012"
    assert result["boundary"]["method"] == "fallback"
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "cover_too_short" not in kinds
    assert "low_confidence_boundary" not in kinds
    assert "no_obligation_checked" not in kinds
    assert "missing_securitizer_file_number" not in kinds
    assert "missing_securitizer_cik" not in kinds


def test_analyze_abs_15g_banner_caption_fragment(tmp_path: Path) -> None:
    _write_case(tmp_path, _SAMPLE_15G_BANNER_FRAGMENT)
    result = analyze_case(
        tmp_path, {"accession": "0000310522-12-000101", "form": "ABS-15G"}
    )
    assert result is not None
    fields = result["form_abs_reports"]
    assert fields["shape"] == "table_fragment"
    assert fields["part_caption"] == {"index": 9, "count": 42}
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_securitizer_file_number" not in kinds
    assert "missing_securitizer_cik" not in kinds
    assert "no_obligation_checked" not in kinds


def test_analyze_abs_15g_banner_on_a_face_stays_a_face(tmp_path: Path) -> None:
    _write_case(
        tmp_path, "15GaFile_01_of_42_0107_0201.htm\n" + _SAMPLE_15G_TEXT
    )
    result = analyze_case(
        tmp_path, {"accession": "0000310522-12-000003", "form": "ABS-15G"}
    )
    assert result is not None
    fields = result["form_abs_reports"]
    assert fields["shape"] == "face"
    assert fields["securitizer_file_number"] == "025-14602"


def test_analyze_abs_15g_mangled_header_fragment(tmp_path: Path) -> None:
    _write_case(tmp_path, _SAMPLE_15G_MANGLED_FRAGMENT)
    result = analyze_case(
        tmp_path, {"accession": "0000310522-13-000189", "form": "ABS-15G"}
    )
    assert result is not None
    fields = result["form_abs_reports"]
    assert fields["shape"] == "table_fragment"
    assert fields["part_caption"] == {"index": 51, "count": 54}
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_securitizer_file_number" not in kinds


def test_summarize_scorecard() -> None:
    reports = [
        {
            **_rep_shell(),
            "accession": "a",
            "family": "ABS",
            "form_abs_reports": {
                "kind": "distribution",
                "issuing_entity_file_number": "001-1",
                "issuing_entity_cik": "0000000001",
                "issuing_entity_name": "X",
                "depositor_file_number": "001-2",
                "distribution_period": {"from": "a", "to": "b"},
            },
            "checkmarks": {},
            "anomalies": [],
        },
        {
            **_rep_shell(),
            "accession": "b",
            "family": "ABS",
            "form_abs_reports": {
                "kind": "securitizer",
                "shape": "table_fragment",
                "table_header_present": True,
                "item_201_detected": False,
            },
            "checkmarks": {},
            "anomalies": [],
        },
    ]
    summary = summarize_cases(reports)
    scorecard = summary["form_abs_reports_scorecard"]
    assert scorecard["kind_counts"] == {"distribution": 1, "securitizer": 1}
    assert scorecard["distribution"]["distribution_period_count"] == 1
    assert scorecard["securitizer"]["table_fragment_count"] == 1
