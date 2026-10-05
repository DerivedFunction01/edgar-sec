"""Contract tests for generic structural matching in cover, TOC, and body."""

from __future__ import annotations

import pytest

from edgar_sec.engine.forms.cover.structure import (
    RE_ITEM_EXACT,
    RE_ITEM_REFERENCE,
    RE_PART,
    RE_PART_REFERENCE,
    SectionKind,
    StructuralRole,
    is_continuation_prose,
    is_exact_heading,
    is_preceding_continuation,
    match_structural_line,
    parse_section_heading,
)


def test_parse_section_heading_reads_a_part_heading_with_its_title() -> None:
    parsed = parse_section_heading("PART II - RISK FACTORS")

    assert parsed is not None
    assert parsed.kind is SectionKind.PART
    assert parsed.identifier == "II"
    assert parsed.canonical_label == "PART II"
    assert parsed.title == "RISK FACTORS"


def test_parse_section_heading_reads_a_decimal_item_identifier() -> None:
    parsed = parse_section_heading("Item 9.01")

    assert parsed is not None
    assert parsed.kind is SectionKind.ITEM
    assert parsed.identifier == "9.01"


def test_parse_section_heading_rejects_leading_prose() -> None:
    assert parse_section_heading("as noted in Item 1, the registrant") is None


def test_parse_section_heading_flags_prose_mentions_when_inline_is_allowed() -> None:
    parsed = parse_section_heading("pursuant to Item 7", allow_inline=True)

    assert parsed is not None
    assert parsed.is_exact_heading is False


def test_parse_section_heading_of_blank_text_is_none() -> None:
    assert parse_section_heading("   ") is None


def test_part_and_item_exact_patterns_reject_dot_leader_rows() -> None:
    assert RE_PART.fullmatch("PART I") is not None
    assert RE_PART.fullmatch("PART I ......... 1") is None
    assert RE_ITEM_EXACT.fullmatch("Item 1. Business") is not None
    assert RE_ITEM_EXACT.fullmatch("ITEM 1A. RISK FACTORS ...... 8") is None


def test_match_structural_line_reports_multiple_references() -> None:
    match = match_structural_line("Item 1 and Part II", 3)

    assert match is not None
    assert match.role == StructuralRole.UNKNOWN
    assert match.is_exact_heading is False
    assert match.reference_count == 2


def test_match_structural_line_rejects_blank_lines() -> None:
    assert match_structural_line("   ", 0) is None
    assert match_structural_line("ordinary prose about widgets", 0) is None


def test_match_structural_line_finds_an_exact_part_heading() -> None:
    match = match_structural_line("PART II", 5)

    assert match is not None
    assert match.role == StructuralRole.PART
    assert match.is_exact_heading is True


def test_a_pipe_delimited_part_is_prose_not_an_exact_heading() -> None:
    match = match_structural_line("| PART II |", 5)

    assert match is not None
    assert match.role == StructuralRole.UNKNOWN
    assert match.is_exact_heading is False


def test_is_exact_heading_is_true_only_for_isolated_headings() -> None:
    assert is_exact_heading("ITEM 15. EXHIBITS") is True
    assert is_exact_heading("ITEM 15. EXHIBITS ....... 40") is False


def test_is_continuation_prose_accepts_lowercase_and_bullet_lines() -> None:
    assert is_continuation_prose("hereof. the registrant agrees") is True
    assert is_continuation_prose("* Item 3. Legal Proceedings") is True
    assert is_continuation_prose("PART I") is False


def test_is_preceding_continuation_reads_trailing_words_and_punctuation() -> None:
    assert is_preceding_continuation("the following documents, including") is True
    assert is_preceding_continuation("Section 12(b):") is True
    assert is_preceding_continuation("Section 12(b)") is False


def test_reference_patterns_come_from_the_shared_toc_vocabulary() -> None:
    assert RE_PART_REFERENCE.search("See PART II") is not None
    assert RE_ITEM_REFERENCE.search("See Item 1A") is not None


@pytest.mark.parametrize(
    "text",
    [
        "PART IV (Continued)",
        "ITEM 1. BUSINESS",
        "Item 1A. Risk Factors",
        "(a) Financial Statements and Schedules",
        "(b) Reports on Form 8-K",
        "(1) Financial Statements",
        "1. General Development of Business",
    ],
)
def test_isolated_headings_are_not_continuation_prose(text: str) -> None:
    assert is_continuation_prose(text) is False


def test_is_continuation_prose_flags_lowercase_outlines_and_references() -> None:
    assert is_continuation_prose("(a) as described in the proxy") is True
    assert is_continuation_prose("(1) Part III is incorporated by reference") is True
