"""Tests for beneficial ownership document parser."""

from __future__ import annotations

from edgar_sec.engine.forms.beneficial_ownership.parser import (
    parse_beneficial_ownership_document,
)
from edgar_sec.engine.forms.cover.models import BoundaryMethod, CoverBoundary
from edgar_sec.engine.forms.normalize import NormalizationResult
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
