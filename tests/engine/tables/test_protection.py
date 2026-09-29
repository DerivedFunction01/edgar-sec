"""Unit tests for edgar_sec.engine.tables.protection."""

from __future__ import annotations

from edgar_sec.engine.tables.protection import (
    ProtectedText,
    mask_tagged_tables,
    restore_tagged_tables,
)


def test_mask_and_restore_tagged_tables() -> None:
    text = "Heading\n<TABLE>\n<S>    <C>\nItem   $100\n</TABLE>\nTrailing text."
    masked, spans = mask_tagged_tables(text)
    assert "<TABLE>" not in masked
    assert "__SEC_TBL_0__" in masked
    assert len(spans) == 1

    restored = restore_tagged_tables(masked, spans)
    assert restored == text


def test_protected_text_context() -> None:
    text = "<TABLE>data</TABLE>"
    pt = ProtectedText(text)
    assert "__SEC_TBL_" in pt.masked
    assert pt.original == text
    assert pt.span_count == 1
