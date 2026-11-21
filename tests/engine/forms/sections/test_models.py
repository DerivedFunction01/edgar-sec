"""Unit tests for section and footnote models, bisect indexing, and extraction."""

from __future__ import annotations

from edgar_sec.engine.forms.sections.models import (
    CandidateKind,
    NotesSequence,
    ResolvedNote,
    ResolvedSection,
    SectionSequence,
)


def test_section_sequence_indexing_and_bisect() -> None:
    text = (
        "COVER PAGE\n"  # line 0: 0..11
        "ITEM 1. BUSINESS\n"  # line 1: 11..28
        "Business description goes here.\n"  # line 2: 28..60
        "ITEM 1A. RISK FACTORS\n"  # line 3: 60..82
        "Risk factors go here.\n"  # line 4: 82..104
        "ITEM 2. PROPERTIES\n"  # line 5: 104..123
        "Properties details.\n"  # line 6: 123..143
    )

    sec1 = ResolvedSection(
        item_identifier="ITEM 1",
        start_line=1,
        end_line=2,
        title="BUSINESS",
        raw_heading="ITEM 1. BUSINESS",
        kind=CandidateKind.STANDARD,
        confidence=0.95,
        start_char=11,
        end_char=60,
    )
    sec1a = ResolvedSection(
        item_identifier="ITEM 1A",
        start_line=3,
        end_line=4,
        title="RISK FACTORS",
        raw_heading="ITEM 1A. RISK FACTORS",
        kind=CandidateKind.STANDARD,
        confidence=0.95,
        start_char=60,
        end_char=104,
    )
    sec2 = ResolvedSection(
        item_identifier="ITEM 2",
        start_line=5,
        end_line=6,
        title="PROPERTIES",
        raw_heading="ITEM 2. PROPERTIES",
        kind=CandidateKind.STANDARD,
        confidence=0.95,
        start_char=104,
        end_char=143,
    )

    seq = SectionSequence(
        family="10-K",
        sections=(sec1, sec1a, sec2),
    )

    # 1. O(1) identifier lookup
    assert seq.get("ITEM 1") == sec1
    assert seq.get("1") == sec1
    assert seq.get("item 1a") == sec1a
    assert seq.get("1A") == sec1a
    assert seq.get("ITEM 2") == sec2
    assert seq.get("ITEM 3") is None

    # 2. O(log S) line lookup via bisect
    assert seq.find_section_for_line(0) is None
    assert seq.find_section_for_line(1) == sec1
    assert seq.find_section_for_line(2) == sec1
    assert seq.find_section_for_line(3) == sec1a
    assert seq.find_section_for_line(4) == sec1a
    assert seq.find_section_for_line(5) == sec2
    assert seq.find_section_for_line(6) == sec2
    assert seq.find_section_for_line(7) is None

    # 3. O(log S) char offset lookup via bisect
    assert seq.find_section_for_offset(5) is None
    assert seq.find_section_for_offset(11) == sec1
    assert seq.find_section_for_offset(35) == sec1
    assert seq.find_section_for_offset(60) == sec1a
    assert seq.find_section_for_offset(90) == sec1a
    assert seq.find_section_for_offset(110) == sec2
    assert seq.find_section_for_offset(200) is None

    # 4. O(1) text extraction
    txt1 = seq.get_text(text, "1")
    assert txt1 == "ITEM 1. BUSINESS\nBusiness description goes here."

    txt1a = seq.get_text(text, "ITEM 1A")
    assert txt1a == "ITEM 1A. RISK FACTORS\nRisk factors go here."


def test_notes_sequence_indexing_and_bisect() -> None:
    text = (
        "NOTES TO CONSOLIDATED FINANCIAL STATEMENTS\n"  # 0..43
        "Note 1. Summary of Operations\n"  # 43..73
        "Operations details.\n"  # 73..93
        "Note 2. Leases\n"  # 93..108
        "Lease details.\n"  # 108..123
    )

    n1 = ResolvedNote(
        note_number=1,
        note_label="NOTE 1",
        start_line=1,
        end_line=2,
        title="Summary of Operations",
        raw_heading="Note 1. Summary of Operations",
        confidence=0.95,
        start_char=43,
        end_char=93,
    )
    n2 = ResolvedNote(
        note_number=2,
        note_label="NOTE 2",
        start_line=3,
        end_line=4,
        title="Leases",
        raw_heading="Note 2. Leases",
        confidence=0.95,
        start_char=93,
        end_char=123,
    )

    notes = NotesSequence(notes=(n1, n2))

    assert notes.get(1) == n1
    assert notes.get(2) == n2
    assert notes.get(3) is None

    assert notes.find_note_for_line(0) is None
    assert notes.find_note_for_line(1) == n1
    assert notes.find_note_for_line(2) == n1
    assert notes.find_note_for_line(3) == n2
    assert notes.find_note_for_line(5) is None

    txt1 = notes.get_text(text, 1)
    assert txt1 == "Note 1. Summary of Operations\nOperations details."
