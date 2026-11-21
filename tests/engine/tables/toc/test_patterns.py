"""TOC row recognition shared by table unwrapping and cover boundary detection."""

from __future__ import annotations

import pytest

from edgar_sec.engine.tables.toc.patterns import (
    RE_ITEM_REFERENCE,
    RE_PAGE_SUFFIX,
    RE_PART_REFERENCE,
    is_toc_row,
    looks_like_toc_row,
    looks_like_toc_tabular,
)


def test_item_and_part_references_match_a_leading_heading() -> None:
    assert RE_ITEM_REFERENCE.match("ITEM 5. MARKET FOR REGISTRANT") is not None
    assert RE_ITEM_REFERENCE.match("ITEM 7A.") is not None
    assert RE_PART_REFERENCE.match("PART I") is not None
    assert RE_PART_REFERENCE.match("PART 1") is not None


@pytest.mark.parametrize(
    ("line", "tabular"),
    [
        ("Item 1 Business                            10", False),
        ("Item 1 Business                            F-1", False),
        ("ITEM 1. BUSINESS .......................... 1", True),
        ("Item 1A. Risk Factors ......... 12", True),
    ],
)
def test_html_toc_rows_are_retained(line: str, tabular: bool) -> None:
    assert looks_like_toc_row(line) is True
    assert looks_like_toc_tabular(line) is tabular


def test_a_leader_less_item_row_with_a_page_suffix_still_counts() -> None:
    assert looks_like_toc_row("Item 1 Business   10") is True
    assert is_toc_row("Item 1 Business   10") is False


def test_a_dot_leader_without_a_part_or_item_reference_is_not_a_toc_row() -> None:
    assert is_toc_row("Risk Factors ......... 5") is False
    assert looks_like_toc_tabular("Risk Factors ......... 5") is True


def test_prose_with_a_trailing_number_is_not_a_toc_row() -> None:
    assert looks_like_toc_row("We recorded 10") is False
    assert looks_like_toc_tabular("We recorded 10") is False


def test_empty_and_pipe_decorated_lines_are_rejected() -> None:
    assert looks_like_toc_row("   ") is False
    assert looks_like_toc_row("|") is False
    assert looks_like_toc_tabular("") is False


def test_roman_and_namespaced_page_suffixes_count() -> None:
    assert RE_PAGE_SUFFIX.search("xii") is not None
    assert RE_PAGE_SUFFIX.search("F-1") is not None
    assert RE_PAGE_SUFFIX.search("no digits") is None
