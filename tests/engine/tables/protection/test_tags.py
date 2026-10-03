"""Exact tagged-table protection.
Covers the published round-trip guarantees: byte-identical restoration, loud
failure on a lost sentinel, offset stability for `ProtectedText`.
"""

from __future__ import annotations

import pytest

from edgar_sec.engine.tables.protection.tags import (
    SENTINEL_PREFIX,
    SENTINEL_SUFFIX,
    ProtectedText,
    TableSpan,
    ensure_table_tag_boundaries,
    find_table_spans,
    mask_tagged_tables,
    restore_tagged_tables,
    strip_table_wrapper_tags,
)

TAGGED = """<TABLE>
<S>     <C>   <C>
Assets   1,000   900
</TABLE>"""


def test_find_table_spans_locates_exact_offsets() -> None:
    text = f"prose before\n\n{TAGGED}\n\nprose after"
    spans = find_table_spans(text)
    assert len(spans) == 1
    assert spans[0].text == TAGGED
    assert spans[0].start == text.find("<TABLE>")
    assert spans[0].end == spans[0].start + len(TAGGED)
    assert spans[0].complete


def test_complete_table_is_masked_and_restored_exactly() -> None:
    text = f"prose before\n\n{TAGGED}\n\nprose after"
    masked, spans = mask_tagged_tables(text)

    assert len(spans) == 1
    assert spans[0].text == TAGGED
    assert TAGGED not in masked
    assert SENTINEL_PREFIX in masked
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


def test_empty_text_yields_no_spans() -> None:
    assert find_table_spans("") == ()
    assert mask_tagged_tables("") == ("", ())


def test_sentinel_collision_disables_masking() -> None:
    text = f"has {SENTINEL_PREFIX}{SENTINEL_SUFFIX}\n<TABLE>\nA 1\n</TABLE>"
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


def test_restore_preserves_inline_table_tags_exactly() -> None:
    first = "<TABLE>\nA 1\n</TABLE>"
    second = "<TABLE>\nB 2\n</TABLE>"
    text = f"prefix {first} suffix {second} tail"

    masked, spans = mask_tagged_tables(text)
    restored = restore_tagged_tables(masked, spans)

    assert restored == text


def test_round_trip_is_byte_identical_for_every_table_shape() -> None:
    cases = (
        TAGGED,
        "<TABLE>only inline</TABLE>",
        "<TABLE>\nunterminated",
        f"{TAGGED}\n{TAGGED}",
        f"lead {TAGGED} trail",
    )
    for text in cases:
        masked, spans = mask_tagged_tables(text)
        assert restore_tagged_tables(masked, spans) == text


def test_masking_hides_table_bytes_from_prose_rewriting() -> None:
    text = f"prose\n\n{TAGGED}\n\nmore prose"
    masked, spans = mask_tagged_tables(text)
    rewritten = masked.replace("prose", "PROSE")
    restored = restore_tagged_tables(rewritten, spans)

    assert "<S>     <C>   <C>" in restored
    assert "PROSE" in restored


def test_line_ranges_report_span_line_span() -> None:
    text = "line0\nline1\n" + TAGGED + "\ntail"
    spans = find_table_spans(text)
    assert len(spans) == 1
    ((start_line, end_line),) = spans[0].line_ranges
    assert (start_line, end_line) == (2, 5)
    assert start_line == text.count("\n", 0, spans[0].start)
    assert end_line == text.count("\n", 0, spans[0].end)


def test_protected_text_exposes_span_partitions() -> None:
    text = f"{TAGGED}\nmid\n<TABLE>\nB 2\n</TABLE>"
    protected = ProtectedText(text)

    assert bool(protected)
    assert protected.span_count == 2
    assert len(protected) == len(text)
    assert len(protected.complete_spans) == 2
    assert protected.unterminated_spans == ()
    assert all(isinstance(s, TableSpan) for s in protected.spans)
    assert protected.original == text
    assert protected.masked != text


def test_protected_text_original_restores_exactly_once() -> None:
    text = f"prose\n{TAGGED}"
    protected = ProtectedText(text)
    first = protected.original
    second = protected.original
    assert first == text
    assert second == text


def test_protected_text_transform_outside_leaves_tables_intact() -> None:
    text = f"prose\n{TAGGED}"
    protected = ProtectedText(text)
    result = protected.transform_outside(str.upper)

    assert result.startswith("PROSE\n")
    assert "<S>     <C>   <C>" in result


def test_protected_text_transform_span_touches_one_table_only() -> None:
    first = "<TABLE>\naaa 1\n</TABLE>"
    second = "<TABLE>\nbbb 2\n</TABLE>"
    text = f"prose\n{first}\nmid\n{second}"
    protected = ProtectedText(text)

    result = protected.transform_span(1, str.upper)

    assert "aaa 1" in result
    assert "AAA 1" not in result
    assert "BBB 2" in result
    assert "bbb 2" not in result
    assert "prose" in result


def test_protected_text_transform_span_rejects_out_of_range() -> None:
    protected = ProtectedText(TAGGED)
    with pytest.raises(IndexError):
        protected.transform_span(5, str.upper)
    with pytest.raises(IndexError):
        protected.transform_span(-1, str.upper)


def test_protected_text_line_preserving_mask_keeps_offsets() -> None:
    text = f"prose\n{TAGGED}\ntail"
    protected = ProtectedText(text)
    masked, spans = protected.line_preserving_mask()

    assert spans == protected.spans
    assert SENTINEL_PREFIX in masked
    assert restore_tagged_tables(masked, spans) == text


def test_protected_text_without_tables_is_falsy_and_passes_through() -> None:
    text = "just prose"
    protected = ProtectedText(text)
    assert not protected
    assert protected.masked == text
    assert protected.original == text
    assert protected.transform_outside(str.upper) == "JUST PROSE"


def test_protected_text_reports_unterminated_spans() -> None:
    text = "prose\n<TABLE>\nopen forever"
    protected = ProtectedText(text)
    assert len(protected.complete_spans) == 0
    assert len(protected.unterminated_spans) == 1


def test_strip_table_wrapper_tags_keeps_body() -> None:
    text = "<TABLE BORDER=1>\n<S>  <C>\nA 1\n</TABLE>"
    stripped = strip_table_wrapper_tags(text)

    assert "<TABLE" not in stripped
    assert "</TABLE>" not in stripped
    assert "<S>  <C>\nA 1" in stripped


def test_ensure_table_tag_boundaries_isolates_open_tag() -> None:
    text = "prose <TABLE>\nA 1\n</TABLE> tail"
    result = ensure_table_tag_boundaries(text)
    assert result == "prose\n<TABLE>\nA 1\n</TABLE>\ntail"


def test_ensure_table_tag_boundaries_leaves_already_isolated_tags() -> None:
    text = "<TABLE>\nA 1\n</TABLE>"
    assert ensure_table_tag_boundaries(text) == text


def test_sentinel_constants_compose_into_the_mask_token() -> None:
    text = TAGGED
    masked, spans = mask_tagged_tables(text)
    token = f"{SENTINEL_PREFIX}{0}{SENTINEL_SUFFIX}"
    assert token in masked
    assert restore_tagged_tables(masked, spans) == text
