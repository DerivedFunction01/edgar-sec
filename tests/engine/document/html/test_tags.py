"""Tests for the HTML tag classification vocabulary.

These sets decide vertical whitespace in output, so the tests pin membership
rather than size: a tag silently reclassified changes the text of every filing
that uses it.
"""

from __future__ import annotations

from edgar_sec.engine.document.html.tags import (
    BLOCK_TAGS,
    CONTAINER_BLOCK_TAGS,
    INLINE_TAGS,
    PARAGRAPH_TAGS,
    TABLE_AND_PRE_TAGS,
)


def test_paragraph_tags_delimit_a_blank_line() -> None:
    assert {"p", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"} <= PARAGRAPH_TAGS
    assert "div" not in PARAGRAPH_TAGS
    assert "li" not in PARAGRAPH_TAGS


def test_container_tags_delimit_a_single_newline() -> None:
    assert {"div", "li", "ul", "ol", "dl", "dt", "dd", "hr"} <= CONTAINER_BLOCK_TAGS
    assert "p" not in CONTAINER_BLOCK_TAGS


def test_table_and_pre_tags_are_blocks() -> None:
    assert {"table", "tbody", "thead", "tfoot", "tr", "td", "th", "pre"} <= (
        TABLE_AND_PRE_TAGS
    )


def test_inline_tags_are_not_blocks() -> None:
    assert {"a", "span", "font", "b", "i", "em", "strong", "sup", "sub"} <= INLINE_TAGS
    assert not (INLINE_TAGS & BLOCK_TAGS)


def test_block_tags_is_the_union_of_the_three_sets() -> None:
    assert BLOCK_TAGS == PARAGRAPH_TAGS | CONTAINER_BLOCK_TAGS | TABLE_AND_PRE_TAGS


def test_classification_sets_are_disjoint_where_it_matters() -> None:
    assert not (PARAGRAPH_TAGS & CONTAINER_BLOCK_TAGS)
    assert not (PARAGRAPH_TAGS & TABLE_AND_PRE_TAGS)
    assert not (CONTAINER_BLOCK_TAGS & TABLE_AND_PRE_TAGS)
