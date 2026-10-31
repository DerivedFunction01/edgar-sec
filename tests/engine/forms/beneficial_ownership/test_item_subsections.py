"""Tests for statutory narrative subsection extraction."""

from __future__ import annotations

from edgar_sec.engine.forms.beneficial_ownership.item_subsections import (
    clean_subsection_value,
    extract_subsections,
)


def test_clean_subsection_value_strips_statutory_label_and_html() -> None:
    raw1 = "Name of Issuer:\nJ.P. Morgan Exchange-Traded Fund Trust"
    assert (
        clean_subsection_value("issuerName", raw1)
        == "J.P. Morgan Exchange-Traded Fund Trust"
    )

    raw2 = "<P><B>Name of Person Filing:</B></P>\nTruist Financial Corporation"
    assert (
        clean_subsection_value("filingPersonName", raw2)
        == "Truist Financial Corporation"
    )

    raw3 = "Address of Principal Business Office or, if none, Residence:\n214 North Tryon Street"
    assert (
        clean_subsection_value("principalBusinessAddress", raw3)
        == "214 North Tryon Street"
    )


def test_extract_subsections_parses_item_1() -> None:
    text = """(a) Name of Issuer:
Owens Illinois Incorporated
(b) Address of Issuer's Principal Executive Offices:
One Michael Owens Way, Perrysburg, OH 43551"""
    fields = extract_subsections(1, text, family="13G")
    assert len(fields) == 2
    assert fields[0].tag == "issuerName"
    assert fields[0].value == "Owens Illinois Incorporated"
    assert fields[1].tag == "issuerAddress"
    assert fields[1].value == "One Michael Owens Way, Perrysburg, OH 43551"


def test_extract_subsections_parses_item_2() -> None:
    text = """Item 2.
(a) Name of Person Filing:
Truist Financial Corporation
(b) Address of Principal Business Office or, if none, Residence:
214 North Tryon Street, Charlotte, NC 28202
(c) Citizenship:
North Carolina"""
    fields = extract_subsections(2, text, family="13G")
    assert len(fields) == 3
    assert fields[0].tag == "filingPersonName"
    assert fields[0].value == "Truist Financial Corporation"
    assert fields[1].tag == "principalBusinessAddress"
    assert fields[1].value == "214 North Tryon Street, Charlotte, NC 28202"
    assert fields[2].tag == "citizenshipOrOrganization"
    assert fields[2].value == "North Carolina"


def test_extract_subsections_parses_13d_item_2_and_5() -> None:
    item2_text = """(a) Alpha Fund.
(b) 123 Main Street, Dover, Delaware 19901.
(c) Private investment fund.
(d) No criminal conviction during the past five years.
(e) No civil proceeding during the past five years.
(f) Delaware."""
    fields2 = extract_subsections(2, item2_text, family="13D")
    assert [f.tag for f in fields2] == [
        "filingPersonName",
        "principalBusinessAddress",
        "principalBusiness",
        "citizenshipOrOrganization",
    ]
    assert fields2[0].value == "Alpha Fund"
    assert fields2[2].value == "Private investment fund"
    assert fields2[3].value == "Delaware."

    item5_text = """(a) 50,000 shares, representing 5.0 percent.
(b) The person has sole voting and dispositive power over the shares.
(c) No transactions during the past sixty days.
(d) No other person has rights to proceeds.
(e) January 1, 2020."""
    fields5 = extract_subsections(5, item5_text, family="13D")
    tag_map5 = {f.tag: f.value for f in fields5}
    assert "percentageOfClassSecurities" in tag_map5
    assert tag_map5["aggregateAmountOwned"] == "50000"
    assert tag_map5["percentOfClass"] == "5.0"
    assert "numberOfShares" in tag_map5
    assert "transactionDesc" in tag_map5


def test_extract_subsections_parses_13g_item_4_ownership() -> None:
    item4_text = """Item 4. Ownership
(a) Amount beneficially owned:
    2,086,925 shares of common stock
(b) Percent of class:
    9.478%
(c) Number of shares as to which the person has:
    (i) Sole power to vote or to direct the vote: 2,086,925.
    (ii) Shared power to vote or to direct the vote: 0.
    (iii) Sole power to dispose or to direct the disposition of: 2,086,925.
    (iv) Shared power to dispose or to direct the disposition of: 0."""
    fields = extract_subsections(4, item4_text, family="13G")
    tag_map = {f.tag: f.value for f in fields}
    assert tag_map["aggregateAmountOwned"] == "2086925"
    assert tag_map["percentOfClass"] == "9.478"
    assert tag_map["soleVotingPower"] == "2086925"
    assert tag_map["sharedVotingPower"] == "0"
    assert tag_map["soleDispositivePower"] == "2086925"
    assert tag_map["sharedDispositivePower"] == "0"


def test_extract_subsections_13g_item_3_and_10() -> None:
    item3_text = """Item 3. Filer Classification
(a) [ ] Broker or dealer
(e) [X] An investment adviser in accordance with Rule 13d-1(b)(1)(ii)(E)
(g) [X] Parent holding company or control person"""
    fields3 = extract_subsections(3, item3_text, family="13G")
    assert len(fields3) == 1
    assert fields3[0].tag == "typeOfReportingPerson"
    assert fields3[0].value == "IA, HC"

    item10_text = """Item 10. Certifications
By signing below I certify that the securities were not acquired and are not held for control purposes."""
    fields10 = extract_subsections(10, item10_text, family="13G")
    assert len(fields10) == 1
    assert fields10[0].tag == "certifications"
    assert (
        fields10[0].value
        == "By signing below I certify that the securities were not acquired and are not held for control purposes."
    )


def test_extract_subsections_13d_item_3_funds() -> None:
    item3_text = """Item 3. Source and Amount of Funds
The Reporting Person acquired the shares using working capital and personal funds."""
    fields3 = extract_subsections(3, item3_text, family="13D")
    assert len(fields3) == 1
    assert fields3[0].tag == "fundType"
    assert fields3[0].value == "WC, PF"


def test_extract_subsections_truncates_at_boundary_and_rejects_narrative_leak() -> None:
    """Verify subsection boundary cuts off next item and discards unresolvable text."""
    leaked_text = """(a) Amount beneficially owned: 1,500,000
(c) Number of shares as to which the person has:
    (iv) Shared power to dispose: Capital Research is deemed owner of 15M shares...
Item 5. Ownership of Five Percent or Less of a Class
If this statement is being filed to report..."""
    fields = extract_subsections(4, leaked_text, family="13G")
    tags = {f.tag: f.value for f in fields}
    assert tags.get("aggregateAmountOwned") == "1500000"
    assert "sharedDispositivePower" not in tags
