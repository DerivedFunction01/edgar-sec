"""Contract tests for TOC-specific regex patterns."""

from __future__ import annotations

import pytest

from edgar_sec.engine.forms.cover.toc.patterns import (
    RE_TOC_HEADING,
    RE_TOC_ITEM,
    RE_TOC_NUMERIC_LABEL,
    RE_TOC_PART_ROW,
    RE_TOC_PART_TEXT,
    WEAK_TOC_HEADINGS,
)


@pytest.mark.parametrize(
    "text",
    ["TABLE OF CONTENTS", "contents", "  | CONTENTS |", "Table of Contents (Parts)"],
)
def test_toc_heading_matches_its_whole_line(text: str) -> None:
    assert RE_TOC_HEADING.match(text) is not None


def test_toc_heading_rejects_a_heading_with_trailing_text() -> None:
    assert RE_TOC_HEADING.match("TABLE OF CONTENTS for Item 1") is None


def test_part_row_captures_the_ordinal() -> None:
    match = RE_TOC_PART_ROW.match("| PART III |")

    assert match is not None
    assert match.group(1) == "III"


def test_spaced_out_part_text_is_recognized() -> None:
    assert RE_TOC_PART_TEXT.search("P A R T I V") is not None


def test_multi_item_row_matches_only_when_a_separator_follows() -> None:
    assert RE_TOC_ITEM.match("ITEMS 1 and 2.") is not None
    assert RE_TOC_ITEM.match("ITEM 1A") is None


def test_numeric_label_pattern_is_anchored() -> None:
    assert RE_TOC_NUMERIC_LABEL.match("1A. Business") is not None
    assert RE_TOC_NUMERIC_LABEL.match("see 1. Business") is None


def test_weak_headings_are_the_promotable_navigation_labels() -> None:
    assert WEAK_TOC_HEADINGS == ("index", "reference", "references")
