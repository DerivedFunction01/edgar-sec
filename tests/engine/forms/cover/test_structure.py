"""Tests for generic PART/ITEM structural matching."""

from __future__ import annotations

from edgar_sec.engine.forms.cover.structure import (
    is_continuation_prose,
    is_exact_heading,
    is_preceding_continuation,
    match_structural_line,
    parse_section_heading,
)


def test_exact_part_heading() -> None:
    match = match_structural_line("PART I", 10)
    assert match is not None
    assert match.role == "part"
    assert match.is_exact_heading is True
    assert match.line == 10


def test_exact_item_heading_with_title() -> None:
    match = match_structural_line("ITEM 1. Business", 3)
    assert match is not None
    assert match.role == "item"
    assert match.is_exact_heading is True


def test_decimal_item_heading() -> None:
    assert is_exact_heading("ITEM 9.01. Financial Statements and Exhibits")
    assert is_exact_heading("ITEM 5.02")
    assert is_exact_heading("ITEM 7.01")


def test_prose_reference_is_not_a_heading() -> None:
    match = match_structural_line("as noted in Item 1 of the Agreement", 4)
    assert match is not None
    assert match.is_exact_heading is False
    assert match.role == "unknown"


def test_continuation_prose_detection() -> None:
    assert is_continuation_prose("hereunder. The registrant has") is True
    assert is_continuation_prose("- the following items") is True
    assert is_continuation_prose("ITEM 1. Business") is False


def test_preceding_continuation_detection() -> None:
    assert is_preceding_continuation("incorporated by reference:") is True
    assert is_preceding_continuation("included in") is False
    assert is_preceding_continuation("as described under") is True
    assert is_preceding_continuation("set forth in") is False
    assert is_preceding_continuation("PART I") is False


def test_blank_line_is_not_structural() -> None:
    assert match_structural_line("   ", 0) is None


def test_parse_section_heading_requires_line_leading_token() -> None:
    assert parse_section_heading("Item 1. Business") is not None
    assert parse_section_heading("pursuant to Item 1") is None


def test_parse_section_heading_inline_mode() -> None:
    parsed = parse_section_heading("pursuant to Item 1", allow_inline=True)
    assert parsed is not None
    assert parsed.is_exact_heading is False
    assert parsed.canonical_label == "ITEM 1"


def test_continued_marker_is_allowed() -> None:
    assert is_exact_heading("PART I (Continued)")
    assert is_exact_heading("ITEM 1. Business (Continued)")


def test_multiple_references_are_counted() -> None:
    match = match_structural_line("See PART I and ITEM 1", 7)
    assert match is not None
    assert match.reference_count == 2
