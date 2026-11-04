from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.forms.form_tender.analysis import (
    analyze_case,
    summarize_cases,
)

_SCHEDULE_TO_TEXT = """\
UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
WASHINGTON, D.C. 20549
SCHEDULE TO
TENDER OFFER STATEMENT UNDER SECTION 14(d)(1) OR 13(e)(1)
OF THE SECURITIES EXCHANGE ACT OF 1934
ACME WIDGETS, INC.
(Name of Subject Company (Issuer))
ACME ACQUISITION CORP.
(Name of Filing Person (Offeror))
Common Stock, par value $0.01 per share
(Title of Class of Securities)
123456108
(CUSIP Number of Class of Securities)
Jane Doe
Acme Acquisition Corp.
100 Main Street, Springfield, IL 62701
(217) 555-0100
(Name, Address and Telephone Number of Person Authorized to Receive Notices
and Communications on Behalf of Filing Persons)
Calculation of Filing Fee
Transaction Valuation: $10,000,000 Amount of Filing Fee: $1,850
Check the appropriate boxes below to designate any transactions to which the
statement relates:
[X] third-party tender offer subject to Rule 14d-1.
[ ] issuer tender offer subject to Rule 13e-4.
[ ] going-private transaction subject to Rule 13e-3.
[ ] amendment to Schedule 13D under Rule 13d-2.
Item 1. Summary Term Sheet
The offer is for all outstanding shares.
Item 2. Subject Company Information
Acme Widgets, Inc. is the subject company.
Item 3. Identity and Background of Filing Person
Acme Acquisition Corp. is the offeror.
Item 4. Terms of the Tender Offer
The offer price is $10.00 per share.
Item 12. Exhibits
Exhibit (a)(1)(A) Offer to Purchase, filed herewith.
"""

_13E3_TEXT = """\
UNITED STATES
SECURITIES AND EXCHANGE COMMISSION
WASHINGTON, D.C. 20549
SCHEDULE 13E-3
RULE 13e-3 TRANSACTION STATEMENT UNDER SECTION 13(e)
OF THE SECURITIES EXCHANGE ACT OF 1934
BETA HOLDINGS, INC.
(Name of the Issuer)
Beta Holdings, Inc.
(Name of Person Filing Statement)
Common Stock, par value $0.01 per share
(Title of Class of Securities)
987654102
(CUSIP Number of Class of Securities)
John Roe
Beta Holdings, Inc.
200 Oak Avenue, Shelbyville, IL 62565
(217) 555-0199
(Name, Address and Telephone Number of Person Authorized to Receive Notices
and Communications on Behalf of Filing Persons)
Item 1. Summary Term Sheet
This statement relates to a going-private merger.
Item 7. Purposes, Alternatives, Reasons and Effects
The board considered alternatives to the merger.
Item 16. Exhibits
Exhibit (a)(3) Merger Agreement.
"""

_13E4_TEXT = """\
SECURITIES AND EXCHANGE COMMISSION
WASHINGTON, D.C. 20549
SCHEDULE 13E-4 ISSUER TENDER OFFER STATEMENT
GAMMA CORPORATION (Name of Issuer)
GAMMA CORPORATION (Name of Person(s) Filing Statement)
Common Stock, $1 Par Value
(Title of Class of Securities)
163 596 109 (CUSIP Number of Class of Securities)
Calculation of Filing Fee
Transaction Valuation $54,630,000 Amount of Filing Fee $10,926
Item 1. Security and Issuer
Gamma Corporation offers to purchase its shares.
Item 9. Material to Be Filed as Exhibits
Exhibit (a)(1) Offer to Purchase.
"""


def _write_case(tmp_path: Path, text: str) -> None:
    ops = tmp_path / "operations"
    ops.mkdir(parents=True)
    (ops / "render_to_txt.txt").write_text(text, encoding="utf-8")


def test_analyze_case_missing_artifact(tmp_path: Path) -> None:
    result = analyze_case(tmp_path, {"accession": "0000000000-00-000000"})
    assert result is None


def test_analyze_schedule_to_cover(tmp_path: Path) -> None:
    _write_case(tmp_path, _SCHEDULE_TO_TEXT)

    result = analyze_case(
        tmp_path, {"accession": "0001193125-23-188435", "form": "SC TO-T"}
    )
    assert result is not None
    assert result["family"] == "SC TO"
    fields = result["form_tender"]
    assert fields["kind"] == "schedule_to"
    assert fields["subject_company"] == "ACME WIDGETS, INC."
    assert fields["filing_persons"] == ("ACME ACQUISITION CORP.",)
    assert fields["class_title"] == "Common Stock, par value $0.01 per share"
    assert fields["cusip"] == "123456108"
    assert fields["notice_contact_present"] is True
    assert fields["fee_table_present"] is True
    assert fields["offer_to_purchase_exhibit"] is True
    assert result["checkmarks"]["third_party_tender_offer"] is True
    assert result["checkmarks"]["issuer_tender_offer"] is False
    assert result["checkmarks"]["designations"] == ("third_party_tender_offer",)
    assert {"ITEM 1", "ITEM 2", "ITEM 4"} <= set(result["taxonomy"]["detected_items"])
    kinds = {a["kind"] for a in result["anomalies"]}
    assert "missing_subject_company" not in kinds
    assert "missing_filing_person" not in kinds
    assert "missing_class_title" not in kinds
    assert "missing_cusip" not in kinds
    assert "missing_notice_contact" not in kinds


def test_analyze_standalone_13e3_uses_its_own_taxonomy(tmp_path: Path) -> None:
    _write_case(tmp_path, _13E3_TEXT)

    result = analyze_case(
        tmp_path, {"accession": "0001140361-26-039675", "form": "SC 13E3"}
    )
    assert result is not None
    fields = result["form_tender"]
    assert fields["kind"] == "going_private"
    assert fields["subject_company"] == "BETA HOLDINGS, INC."
    assert "ITEM 16" in result["taxonomy"]["detected_items"]


def test_analyze_13e4_same_line_cover(tmp_path: Path) -> None:
    _write_case(tmp_path, _13E4_TEXT)

    result = analyze_case(
        tmp_path, {"accession": "0000950152-99-009866", "form": "SC 13E4"}
    )
    assert result is not None
    fields = result["form_tender"]
    assert fields["kind"] == "issuer_tender_predecessor"
    assert fields["subject_company"] == "GAMMA CORPORATION"
    assert fields["filing_persons"] == ("GAMMA CORPORATION",)
    assert fields["cusip"] == "163596109"
    assert {"ITEM 1", "ITEM 9"} <= set(result["taxonomy"]["detected_items"])


_ERA_CAPTIONS_TEXT = """\
SECURITIES AND EXCHANGE COMMISSION
WASHINGTON, D.C. 20549
SCHEDULE 14D-1
TENDER OFFER STATEMENT PURSUANT TO SECTION 14(d)(1)
DELTA INDUSTRIES, INC.
(Exact name of Subject Company)
EPSILON CORP.
(Name of issuer and person filing statement)
Common Stock, par value $0.01 per share
(INCLUDING THE ASSOCIATED COMMON STOCK PURCHASE RIGHTS)
(TITLE OF CLASS OF SECURITIES)
170021109
(CUSIP NUMBER OF CLASS OF SECURITIES)
Jane Doe, Epsilon Corp., 100 Main Street
(Name, Address and Telephone Number of Persons Authorized to Receive
Notice and Communications on Behalf of Bidders)
Item 1. Security and Subject Company
Epsilon Corp. offers to purchase the shares.
Item 11. Material to Be Filed as Exhibits
Exhibit (a)(1) Offer to Purchase.
"""


def test_analyze_era_caption_variants(tmp_path: Path) -> None:
    _write_case(tmp_path, _ERA_CAPTIONS_TEXT)

    result = analyze_case(
        tmp_path, {"accession": "0000891618-97-004064", "form": "SC 14D1/A"}
    )
    assert result is not None
    fields = result["form_tender"]
    assert fields["kind"] == "third_party_predecessor"
    assert fields["subject_company"] == "DELTA INDUSTRIES, INC."
    assert fields["filing_persons"] == ("EPSILON CORP.",)
    assert fields["class_title"] == (
        "Common Stock, par value $0.01 per share "
        "(INCLUDING THE ASSOCIATED COMMON STOCK PURCHASE RIGHTS)"
    )
    assert fields["cusip"] == "170021109"
    assert fields["notice_contact_present"] is True
    assert {"ITEM 1", "ITEM 11"} <= set(result["taxonomy"]["detected_items"])


def test_summarize_cases_aggregates_scorecard(tmp_path: Path) -> None:
    reports = []
    for name, text, accession, form in (
        ("to", _SCHEDULE_TO_TEXT, "0001193125-23-188435", "SC TO-T"),
        ("e3", _13E3_TEXT, "0001140361-26-039675", "SC 13E3"),
    ):
        case = tmp_path / name
        case.mkdir()
        _write_case(case, text)
        rep = analyze_case(case, {"accession": accession, "form": form})
        assert rep is not None
        reports.append(rep)

    summary = summarize_cases(reports)
    scorecard = summary["form_tender_scorecard"]
    assert scorecard["kind_counts"] == {"schedule_to": 1, "going_private": 1}
    assert scorecard["cusip_count"] == 2
    assert scorecard["designation_counts"]["third_party_tender_offer"] == 1
