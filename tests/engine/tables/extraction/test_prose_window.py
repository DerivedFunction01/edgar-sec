"""Prose-window grain: filer status decided from the window."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.competition import GeometryText
from edgar_sec.engine.tables.extraction.context import TableContext
from edgar_sec.engine.tables.extraction.prose_window import (
    classify_filer_status,
    is_checkbox_fragment,
    read_filer_status,
    window_text,
)

_BLOCK = (
    "Check the appropriate box to designate the filing: "
    "☐ Large accelerated filer ☑ Accelerated filer "
    "☐ Non-accelerated filer ☐ Smaller reporting company "
    "☐ Emerging growth company"
)


def _context(prose_before: str) -> TableContext:
    geometry = TableGeometry(
        table_index=0,
        render_result=TableRenderResult(
            ascii_text="",
            resolved_grid=ResolvedGrid(
                rows=(), column_alignments=(), column_widths=(), header_row_count=0
            ),
            confidence=1.0,
        ),
    )
    return TableContext(geometry=geometry, prose_before=prose_before)


def test_window_is_bounded_and_normalized() -> None:
    window = window_text("x " * 5000, "Caption", "y " * 5000)
    assert len(window) <= 4000


def test_reads_the_marked_category_from_prose() -> None:
    reading = read_filer_status(_BLOCK)
    assert reading is not None
    assert reading.decided
    assert reading.marked == ("accelerated filer",)
    assert "large accelerated filer" in reading.present


def test_lone_mention_is_not_a_block() -> None:
    assert read_filer_status("The accelerated filer filed early.") is None


def test_unmarked_block_is_undecided_not_wrong() -> None:
    text = _BLOCK.replace("☑", "☐")
    reading = read_filer_status(text)
    assert reading is not None
    assert not reading.decided
    assert reading.marked == ()


def test_fragment_detection_uses_grain_not_vocabulary() -> None:
    fragment = GeometryText(caption="", stubs=("☑", "☐"))
    assert is_checkbox_fragment(fragment)
    grid = GeometryText(caption="", stubs=tuple(f"row {i}" for i in range(20)))
    assert not is_checkbox_fragment(grid)


def test_classify_decides_fragment_from_its_window() -> None:
    context = _context(_BLOCK)
    fragment = GeometryText(caption="", stubs=("☑ accelerated filer",))
    reading = classify_filer_status(context, fragment)
    assert reading is not None
    assert reading.marked == ("accelerated filer",)
    assert reading.grain == "prose_window"
