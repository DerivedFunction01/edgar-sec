"""Tests for beneficial ownership document parser."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from edgar_sec.domain.forms.families.processing_profiles import get_family_entry
from edgar_sec.engine.forms.beneficial_ownership.parser import (
    parse_beneficial_ownership_document,
)
from edgar_sec.engine.forms.beneficial_ownership.render_to_xml import (
    build_beneficial_ownership_xml,
)
from edgar_sec.engine.forms.common.unparsed import deserialize_unparsed_sections
from edgar_sec.engine.forms.cover.models import BoundaryMethod, CoverBoundary
from edgar_sec.engine.forms.normalize import NormalizationResult
from edgar_sec.engine.forms.sections.items.detector import detect_section_sequence
from edgar_sec.engine.forms.sections.models import (
    CandidateKind,
    ResolvedSection,
    SectionSequence,
)

_SAMPLE_TEXT = """SCHEDULE 13D
Acme Corp
(Name of Issuer)
123456789
(CUSIP Number)

1. NAMES OF REPORTING PERSONS
   Alpha Fund
2. CHECK THE APPROPRIATE BOX IF A MEMBER OF A GROUP
   (b) [X]
3. SEC USE ONLY
4. SOURCE OF FUNDS
   WC
5. CHECK BOX IF DISCLOSURE OF LEGAL PROCEEDINGS
   [ ]
6. CITIZENSHIP OR PLACE OF ORGANIZATION
   Delaware
7. SOLE VOTING POWER
   100,000
8. SHARED VOTING POWER
   0
9. SOLE DISPOSITIVE POWER
   100,000
10. SHARED DISPOSITIVE POWER
    0
11. AGGREGATE AMOUNT BENEFICIALLY OWNED
    100,000
12. CHECK BOX IF AGGREGATE AMOUNT EXCLUDES CERTAIN SHARES
    [ ]
13. PERCENT OF CLASS
    5.0%
14. TYPE OF REPORTING PERSON
    PN

Item 1. Security and Issuer.
This statement relates to common stock.

Item 2. Identity and Background.
Alpha Fund is a private fund.

SIGNATURE
After reasonable inquiry and to the best of my knowledge, I certify that the information set forth in this statement is true, complete and correct.
Dated: January 1, 2020
By: /s/ John Doe
Name: John Doe
Title: Manager
"""


def test_parse_beneficial_ownership_document_assembles_model() -> None:
    lines = _SAMPLE_TEXT.splitlines()
    item1_line = next(i for i, l in enumerate(lines) if "Item 1." in l)
    item2_line = next(i for i, l in enumerate(lines) if "Item 2." in l)
    sig_line = next(i for i, l in enumerate(lines) if "SIGNATURE" in l)
    sections = SectionSequence(
        family="13D",
        sections=(
            ResolvedSection(
                item_identifier="ITEM 1",
                start_line=item1_line,
                end_line=item2_line,
                title="Security and Issuer",
                raw_heading="Item 1. Security and Issuer.",
                kind=CandidateKind.STANDARD,
                confidence=1.0,
            ),
            ResolvedSection(
                item_identifier="ITEM 2",
                start_line=item2_line,
                end_line=sig_line,
                title="Identity and Background",
                raw_heading="Item 2. Identity and Background.",
                kind=CandidateKind.STANDARD,
                confidence=1.0,
            ),
        ),
    )
    result = NormalizationResult(
        text=_SAMPLE_TEXT,
        family="13D",
        representation="ascii",
        cover_boundary=CoverBoundary(
            start_line=0,
            end_line=item1_line,
            end_offset=0,
            method=BoundaryMethod.STRUCTURAL,
            confidence=1.0,
        ),
        sections=sections,
    )
    doc = parse_beneficial_ownership_document(result, form="13D")
    assert doc.issuer.issuer_name == "Acme Corp"
    assert doc.issuer.cusip == "123456789"
    assert len(doc.reporting_persons) == 1
    item1 = doc.reporting_persons[0].first_item(1)
    assert item1 is not None and item1.value == "Alpha Fund"
    item7 = doc.reporting_persons[0].first_item(7)
    assert item7 is not None and item7.value == "100,000"
    assert len(doc.items1_to_7) == 2
    assert doc.items1_to_7[0].number == 1
    assert "common stock" in doc.items1_to_7[0].text
    assert doc.signature_block is not None


def test_parser_ignores_item_references_in_the_cover_when_finding_body_sections() -> (
    None
):
    text = _SAMPLE_TEXT.replace(
        "\nItem 1. Security and Issuer.",
        "\nSeries A common stock: 10,000 shares (see Items 4 and 5)."
        "\nItem 1. Security and Issuer.",
    )
    lines = text.splitlines()
    item1_line = next(i for i, line in enumerate(lines) if line.startswith("Item 1."))
    cover_end = sum(len(line) + 1 for line in lines[:item1_line])
    family_entry = get_family_entry("13D")
    assert family_entry is not None
    sequence = detect_section_sequence(
        text,
        family="13D",
        taxonomy_items=family_entry.taxonomy_items,
    )
    assert any(section.item_identifier == "ITEM 4" for section in sequence.sections)
    result = NormalizationResult(
        text=text,
        family="13D",
        representation="ascii",
        cover_boundary=CoverBoundary(
            start_line=0,
            end_line=item1_line,
            end_offset=cover_end,
            method=BoundaryMethod.FALLBACK,
            confidence=0.7,
        ),
        sections=sequence,
    )

    document = parse_beneficial_ownership_document(result, form="13D")

    assert [item.number for item in document.narrative_items] == [1, 2]
    assert "Series A common stock" not in document.narrative_items[0].text


def test_parser_maps_known_item_subparts_and_preserves_unmapped_text() -> None:
    text = _SAMPLE_TEXT.replace(
        "Alpha Fund is a private fund.",
        "(a) Alpha Fund.\n"
        "(b) 123 Main Street, Dover, Delaware 19901.\n"
        "(c) Private investment fund.\n"
        "(d) No criminal conviction during the past five years.\n"
        "(e) No civil proceeding during the past five years.\n"
        "(f) Delaware.\n",
    ).replace(
        "SIGNATURE\n",
        "Item 5. Interest in Securities of the Issuer.\n"
        "(a) 50,000 shares, representing 5.0 percent.\n"
        "(b) The person has sole voting and dispositive power over the shares.\n"
        "(c) No transactions during the past sixty days.\n"
        "(d) No other person has rights to proceeds.\n"
        "(e) January 1, 2020.\n"
        "SIGNATURE\n",
    )
    lines = text.splitlines()
    item1_line = next(i for i, line in enumerate(lines) if line.startswith("Item 1."))
    cover_end = sum(len(line) + 1 for line in lines[:item1_line])
    result = NormalizationResult(
        text=text,
        family="13D",
        representation="ascii",
        cover_boundary=CoverBoundary(
            start_line=0,
            end_line=item1_line,
            end_offset=cover_end,
            method=BoundaryMethod.STRUCTURAL,
            confidence=1.0,
        ),
        sections=SectionSequence(family="13D", sections=()),
    )

    document = parse_beneficial_ownership_document(result, form="13D")
    output = build_beneficial_ownership_xml(document)
    xml = ET.fromstring(output.content)
    namespace = {"s": "http://www.sec.gov/edgar/schedule13D"}
    item2 = xml.find(".//s:Item2", namespace)
    item5 = xml.find(".//s:Item5", namespace)
    assert item2 is not None and item5 is not None
    assert [child.tag.rsplit("}", 1)[-1] for child in item2] == [
        "filingPersonName",
        "principalBusinessAddress",
        "principalBusiness",
        "citizenshipOrOrganization",
    ]
    assert [child.tag.rsplit("}", 1)[-1] for child in item5] == [
        "percentageOfClassSecurities",
        "numberOfShares",
        "transactionDesc",
        "listOfShareholders",
        "date5PercentOwnership",
    ]
    assert any(
        section.role == "item2.unparsed" for section in document.unparsed_sections
    )
    assert (
        xml.find(".//{http://www.sec.gov/edgar/schedule13D}extractionProvenance")
        is None
    )
    assert xml.find(".//{http://www.sec.gov/edgar/schedule13D}unparsedSections") is None
    sections = deserialize_unparsed_sections(output.sidecars[0].content)
    item2_unparsed = next(
        section for section in sections if section["role"] == "item2.unparsed"
    )
    assert item2_unparsed["content"] in text


def test_parser_reads_signatures_from_sec_table_rows() -> None:
    text = _SAMPLE_TEXT.replace(
        "SIGNATURE\n"
        "After reasonable inquiry and to the best of my knowledge, I certify that "
        "the information set forth in this statement is true, complete and correct.\n"
        "Dated: January 1, 2020\n"
        "By: /s/ John Doe\n"
        "Name: John Doe\n"
        "Title: Manager",
        "SIGNATURE\n"
        "June 25, 2003 Date /s/ Kerry Samovar Signature Kerry Samovar "
        "Vice President Name/Title\n"
        "June 25, 2003 Date /s/ Joanne Hawkins Signature Joanne Hawkins "
        "Vice President Name/Title",
    )
    lines = text.splitlines()
    item1_line = next(i for i, line in enumerate(lines) if line.startswith("Item 1."))
    cover_end = sum(len(line) + 1 for line in lines[:item1_line])
    family_entry = get_family_entry("13D")
    assert family_entry is not None
    result = NormalizationResult(
        text=text,
        family="13D",
        representation="ascii",
        cover_boundary=CoverBoundary(
            start_line=0,
            end_line=item1_line,
            end_offset=cover_end,
            method=BoundaryMethod.STRUCTURAL,
            confidence=1.0,
        ),
        sections=detect_section_sequence(
            text, family="13D", taxonomy_items=family_entry.taxonomy_items
        ),
    )

    document = parse_beneficial_ownership_document(result, form="13D")

    assert document.signature_block is not None
    assert [signer.name for signer in document.signature_block.signatories] == [
        "Kerry Samovar",
        "Joanne Hawkins",
    ]
    assert [signer.date for signer in document.signature_block.signatories] == [
        "2003-06-25",
        "2003-06-25",
    ]


def test_parser_does_not_truncate_cover_on_checkbox_aliases() -> None:
    text = """UNITED STATES SECURITIES AND EXCHANGE COMMISSION
SCHEDULE 13G
Check the appropriate box to designate the rule pursuant to which this Schedule is filed:
[X] Rule 13d-1(b)
[ ] Rule 13d-1(c)

CUSIP No. 123456789
1. Names of Reporting Persons
Acme Management LLC
4. Citizenship or Place of Organization
Delaware
11. Percent of Class
5.5%
12. Type of Reporting Person
IA

Item 1.
(a) Name of Issuer: Target Corp
Item 2.
(a) Name of Person Filing: Acme Management LLC
Item 3.
If this statement is filed pursuant to 240.13d-1(b): Investment Adviser
Item 4. Ownership
(a) Amount beneficially owned: 500,000
SIGNATURE
Dated: February 14, 2020
By: /s/ John Doe
"""
    family_entry = get_family_entry("13G")
    assert family_entry is not None
    result = NormalizationResult(
        text=text,
        family="13G",
        representation="ascii",
        cover_boundary=CoverBoundary(
            start_line=0,
            end_line=20,
            end_offset=300,
            method=BoundaryMethod.STRUCTURAL,
            confidence=1.0,
        ),
        sections=detect_section_sequence(
            text, family="13G", taxonomy_items=family_entry.taxonomy_items
        ),
    )

    doc = parse_beneficial_ownership_document(result, form="SC 13G")
    assert len(doc.reporting_persons) == 1
    assert (
        doc.reporting_persons[0].first_item("reportingPersonName").value
        == "Acme Management LLC"
    )
    assert doc.issuer.event_date == "2020-02-14"
    assert len(doc.narrative_items) >= 3


def test_cover_end_bounded_by_body_sections_when_boundary_premature() -> None:
    text = """SCHEDULE 13G
Target Corp
(Name of Issuer)
123456789
(CUSIP Number)

1. Names of Reporting Persons: Acme Management LLC
9. Aggregate Amount Beneficially Owned: 500,000
11. Percent of Class: 5.5%
12. Type of Reporting Person: IA

Item 1(a). Name of Issuer: Target Corp
Item 4. Ownership: 500,000 shares
SIGNATURE
Dated: February 14, 2020
By: /s/ John Doe
"""
    family_entry = get_family_entry("13G")
    assert family_entry is not None
    result = NormalizationResult(
        text=text,
        family="13G",
        representation="ascii",
        cover_boundary=CoverBoundary(
            start_line=0,
            end_line=4,
            end_offset=50,
            method=BoundaryMethod.FALLBACK,
            confidence=0.5,
        ),
        sections=detect_section_sequence(
            text, family="13G", taxonomy_items=family_entry.taxonomy_items
        ),
    )
    doc = parse_beneficial_ownership_document(result, form="SC 13G")
    assert len(doc.reporting_persons) == 1
    assert (
        doc.reporting_persons[0].first_item("reportingPersonName").value
        == "Acme Management LLC"
    )


def test_narrative_event_date_fallback_when_absent_on_cover_and_sig() -> None:
    text = """SCHEDULE 13G
Target Corp
(Name of Issuer)
123456789
(CUSIP Number)

1. Names of Reporting Persons: Acme Management LLC
9. Aggregate Amount Beneficially Owned: 500,000
11. Percent of Class: 5.5%
12. Type of Reporting Person: IA

Item 1.
(a) Name of Issuer: Target Corp
Item 4. Ownership
As of December 31, 2019, Acme beneficially owned 500,000 shares.
SIGNATURE
By: /s/ John Doe
"""
    family_entry = get_family_entry("13G")
    assert family_entry is not None
    result = NormalizationResult(
        text=text,
        family="13G",
        representation="ascii",
        cover_boundary=CoverBoundary(
            start_line=0,
            end_line=11,
            end_offset=200,
            method=BoundaryMethod.STRUCTURAL,
            confidence=1.0,
        ),
        sections=detect_section_sequence(
            text, family="13G", taxonomy_items=family_entry.taxonomy_items
        ),
    )
    doc = parse_beneficial_ownership_document(result, form="SC 13G")
    assert doc.issuer.event_date == "2019-12-31"


def test_narrative_ownership_fallback_when_cover_slots_missing() -> None:
    text = """SCHEDULE 13G
Target Corp
(Name of Issuer)
123456789
(CUSIP Number)

1. Names of Reporting Persons: Acme Management LLC
9. Aggregate Amount Beneficially Owned: See Item 4
11. Percent of Class: See Item 4
12. Type of Reporting Person: IA

Item 1.
(a) Name of Issuer: Target Corp
Item 4. Ownership
(a) Amount beneficially owned: 1,250,000 shares
(b) Percent of class: 7.8%
(c) Number of shares as to which the person has:
    (i) Sole power to vote or to direct the vote: 1,250,000
    (ii) Shared power to vote or to direct the vote: 0
    (iii) Sole power to dispose or to direct the disposition of: 1,250,000
    (iv) Shared power to dispose or to direct the disposition of: 0
SIGNATURE
Dated: February 14, 2020
By: /s/ John Doe
"""
    family_entry = get_family_entry("13G")
    assert family_entry is not None
    result = NormalizationResult(
        text=text,
        family="13G",
        representation="ascii",
        cover_boundary=CoverBoundary(
            start_line=0,
            end_line=11,
            end_offset=200,
            method=BoundaryMethod.STRUCTURAL,
            confidence=1.0,
        ),
        sections=detect_section_sequence(
            text, family="13G", taxonomy_items=family_entry.taxonomy_items
        ),
    )
    doc = parse_beneficial_ownership_document(result, form="SC 13G")
    assert len(doc.reporting_persons) == 1
    rp = doc.reporting_persons[0]
    assert rp.first_item("reportingPersonName").value == "Acme Management LLC"
    assert rp.first_item("aggregateAmountOwned").value == "1250000"
    assert rp.first_item("percentOfClass").value == "7.8"
    assert rp.first_item("soleVotingPower").value == "1250000"
    assert rp.first_item("sharedVotingPower").value == "0"


def test_narrative_ownership_fallback_13d_item_5() -> None:
    text = """SCHEDULE 13D
Target Corp
(Name of Issuer)
123456789
(CUSIP Number)

1. Names of Reporting Persons: Alpha Investor LLC
11. Aggregate Amount Beneficially Owned: See Item 5
13. Percent of Class: See Item 5
14. Type of Reporting Person: IA

Item 1. Security and Issuer.
Common stock of Target Corp.

Item 5. Interest in Securities of the Issuer.
(a) Alpha Investor LLC beneficially owns an aggregate of 4,500,000 shares, representing 14.2% of the class.
(b) Sole voting power: 4,500,000. Shared voting power: 0.

SIGNATURE
Dated: October 20, 2020
By: /s/ Jane Smith
"""
    family_entry = get_family_entry("13D")
    assert family_entry is not None
    result = NormalizationResult(
        text=text,
        family="13D",
        representation="ascii",
        cover_boundary=CoverBoundary(
            start_line=0,
            end_line=11,
            end_offset=200,
            method=BoundaryMethod.STRUCTURAL,
            confidence=1.0,
        ),
        sections=detect_section_sequence(
            text, family="13D", taxonomy_items=family_entry.taxonomy_items
        ),
    )
    doc = parse_beneficial_ownership_document(result, form="SC 13D")
    assert len(doc.reporting_persons) == 1
    rp = doc.reporting_persons[0]
    assert rp.first_item("reportingPersonName").value == "Alpha Investor LLC"
    assert rp.first_item("aggregateAmountOwned").value == "4500000"
    assert rp.first_item("percentOfClass").value == "14.2"


def test_zero_ownership_symmetric_normalization() -> None:
    text = """SCHEDULE 13G
Acme Corp
(Name of Issuer)
123456789
(CUSIP Number)

1. Names of Reporting Persons: Investor LLC
11. Percent of Class: 0%
12. Type of Reporting Person: IA

Item 1. Name of Issuer: Acme Corp
SIGNATURE
Dated: October 20, 2020
By: /s/ Jane Smith
"""
    boundary = CoverBoundary(
        start_line=0,
        end_line=9,
        end_offset=0,
        method=BoundaryMethod.STRUCTURAL,
        confidence=1.0,
    )
    result = NormalizationResult(
        text=text,
        family="13G",
        representation="ascii",
        cover_boundary=boundary,
    )
    doc = parse_beneficial_ownership_document(result, form="SC 13G")
    assert len(doc.reporting_persons) == 1
    rp = doc.reporting_persons[0]
    assert rp.first_item("percentOfClass").value == "0%"
    assert rp.first_item("aggregateAmountOwned").value == "0"


def test_signature_lookback_preceding_date() -> None:
    text = """SCHEDULE 13G
Beta Inc
(Name of Issuer)
123456789
(CUSIP Number)

1. Names of Reporting Persons: Gamma Capital
9. Aggregate Amount: 50,000
11. Percent of Class: 5.1%
12. Type of Reporting Person: IA

Item 1. Name of Issuer: Beta Inc

February 5, 2004

Date
/s/ John Doe
Signature
John Doe, Principal
"""
    boundary = CoverBoundary(
        start_line=0,
        end_line=9,
        end_offset=0,
        method=BoundaryMethod.STRUCTURAL,
        confidence=1.0,
    )
    result = NormalizationResult(
        text=text,
        family="13G",
        representation="ascii",
        cover_boundary=boundary,
    )
    doc = parse_beneficial_ownership_document(result, form="SC 13G")
    assert doc.issuer.event_date == "2004-02-05"
    assert doc.signature_block is not None
    assert doc.signature_block.signatories[0].name == "John Doe"
    assert doc.signature_block.signatories[0].date == "2004-02-05"
