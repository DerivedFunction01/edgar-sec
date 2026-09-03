"""Contract tests for exact tagged-table protection."""

from __future__ import annotations

import pytest

from defs.tables.protection import mask_tagged_tables, restore_tagged_tables

TAGGED = """<TABLE>
<S>     <C>   <C>
Assets   1,000   900
</TABLE>"""


def test_complete_table_is_masked_and_restored_exactly() -> None:
    text = f"prose before\n\n{TAGGED}\n\nprose after"
    masked, spans = mask_tagged_tables(text)

    assert len(spans) == 1
    assert spans[0].text == TAGGED
    assert spans[0].complete
    assert TAGGED not in masked
    assert "\x00" in masked
    assert restore_tagged_tables(masked, spans) == text


def test_unclosed_table_is_protected_through_end() -> None:
    tail = "<TABLE>\n<S>  <C>\nAssets 10 20\nnever closed"
    text = f"prose\n\n{tail}"
    masked, spans = mask_tagged_tables(text)

    assert len(spans) == 1
    assert not spans[0].complete
    assert spans[0].end == len(text)
    assert restore_tagged_tables(masked, spans) == text


def test_multiple_tables_restore_in_order() -> None:
    first = "<TABLE>\nA 1\n</TABLE>"
    second = "<TABLE>\nB 2\n</TABLE>"
    text = f"p1\n\n{first}\n\nmiddle\n\n{second}\n\np2"
    masked, spans = mask_tagged_tables(text)

    assert len(spans) == 2
    assert spans[0].text == first
    assert spans[1].text == second
    assert restore_tagged_tables(masked, spans) == text


def test_document_without_tables_is_unchanged() -> None:
    text = "plain prose\nwith lines\nno tables"
    masked, spans = mask_tagged_tables(text)
    assert masked == text
    assert spans == ()


def test_sentinel_collision_disables_masking() -> None:
    text = "has NUL\x00byte\n<TABLE>\nA 1\n</TABLE>"
    masked, spans = mask_tagged_tables(text)
    assert masked == text
    assert spans == ()


def test_case_insensitive_table_tags() -> None:
    text = "<table>\nA 1\n</Table>"
    masked, spans = mask_tagged_tables(text)
    assert len(spans) == 1
    assert restore_tagged_tables(masked, spans) == text


def test_missing_sentinel_at_restore_raises() -> None:
    _, spans = mask_tagged_tables(f"pre\n\n{TAGGED}")
    assert spans
    with pytest.raises(ValueError, match="sentinel"):
        restore_tagged_tables("sentinel removed", spans)


def test_nested_adjacent_tables_span_separately() -> None:
    first = "<TABLE><S><C>A 1</TABLE>"
    second = "<TABLE><S><C>B 2</TABLE>"
    text = f"{first}\n{second}"
    masked, spans = mask_tagged_tables(text)
    assert len(spans) == 2
    assert restore_tagged_tables(masked, spans) == text
