"""Contract tests for masked-to-original offset translation."""

from __future__ import annotations

from edgar_sec.engine.forms.cover.checkmarks.frames import (
    build_masked_offset_translator,
)
from edgar_sec.engine.tables.protection.tags import TableSpan, mask_tagged_tables


def test_offsets_before_any_table_are_unchanged() -> None:
    masked, spans = mask_tagged_tables("alpha\nbeta\n<TABLE>\nx\n</TABLE>\ntail\n")
    translate = build_masked_offset_translator(masked, spans)

    assert spans
    assert translate(0) == 0
    assert translate(masked.index("beta")) == "alpha\nbeta".index("b")


def test_offsets_after_a_sentinel_are_shifted_back_to_the_original_frame() -> None:
    original = "alpha\n<TABLE>\nwide cell content\n</TABLE>\ntail\n"
    masked, spans = mask_tagged_tables(original)
    translate = build_masked_offset_translator(masked, spans)

    masked_tail = masked.index("tail")
    assert translate(masked_tail) == original.index("tail")


def test_an_offset_inside_a_sentinel_maps_to_the_span_start() -> None:
    original = "alpha\n<TABLE>\nwide cell content\n</TABLE>\ntail\n"
    masked, spans = mask_tagged_tables(original)
    translate = build_masked_offset_translator(masked, spans)

    assert spans
    inside = masked.index("__SEC_TBL_0__") + 3
    assert translate(inside) == spans[0].start


def test_no_tables_means_the_identity_translation() -> None:
    translate = build_masked_offset_translator("plain text", ())

    assert translate(6) == 6


def test_a_sentinel_that_is_absent_from_the_masked_text_is_skipped() -> None:
    masked, _spans = mask_tagged_tables("alpha\n<TABLE>\nx\n</TABLE>\n")
    translate = build_masked_offset_translator(
        masked.replace("__SEC_TBL_0__", ""),
        (TableSpan(6, 6 + 18, "<TABLE>\nx\n</TABLE>"),),
    )

    assert translate(0) == 0
