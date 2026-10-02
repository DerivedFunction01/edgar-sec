"""The cheap text-only grid scan used to pre-filter layout tables."""

from __future__ import annotations

from edgar_sec.engine.document.html.tree import parse_html
from edgar_sec.engine.tables.ascii_html.quick_grid import quick_extract_table_grid
from edgar_sec.engine.tables.false_tables.detector import is_false_grid
from edgar_sec.engine.tables.false_tables.unwrapper import unwrap_grid


def _scan(html: str):
    node = parse_html(html).css_first("table")
    assert node is not None
    return quick_extract_table_grid(node)


def test_a_plain_grid_returns_padded_rows_of_normalized_text() -> None:
    grid = _scan("<table><tr><td>Risk Factors</td><td>item 1a</td></tr></table>")
    assert grid == (("Risk Factors", "item 1a"),)
    assert is_false_grid(grid) is False
    assert unwrap_grid(grid) == "Risk Factors item 1a"


def test_a_ragged_grid_is_padded_to_a_uniform_width() -> None:
    grid = _scan("<table><tr><td>a</td><td>b</td></tr><tr><td>c</td></tr></table>")
    assert grid == (("a", "b"), ("c", ""))


def test_a_table_with_no_cells_returns_an_empty_grid() -> None:
    assert _scan("<table></table>") == ()


def test_cell_text_is_whitespace_normalized() -> None:
    grid = _scan("<table><tr><td>a\xa0 b</td><td>x   y</td></tr></table>")
    assert grid == (("a b", "x y"),)


def test_a_colspan_returns_none_so_the_full_extraction_is_required() -> None:
    assert _scan("<table><tr><td colspan='2'>a</td></tr></table>") is None


def test_a_rowspan_returns_none() -> None:
    assert _scan("<table><tr><td rowspan='2'>a</td></tr></table>") is None


def test_a_non_integer_colspan_returns_none_rather_than_guessing() -> None:
    assert _scan("<table><tr><td colspan='two'>a</td></tr></table>") is None


def test_a_nested_table_returns_none() -> None:
    assert (
        _scan(
            "<table><tr><td>outer<table><tr><td>inner</td></tr></table></td></tr></table>"
        )
        is None
    )


def test_a_thead_or_tbody_section_is_read_directly() -> None:
    grid = _scan(
        "<table><thead><tr><th>a</th><th>b</th></tr></thead>"
        "<tbody><tr><td>1</td><td>2</td></tr></tbody></table>"
    )
    assert grid == (("a", "b"), ("1", "2"))


def test_a_scan_that_returns_a_grid_is_usable_by_the_detector_and_unwrapper() -> None:
    grid = _scan(
        "<table><tr><td>1. first</td><td>alpha prose</td></tr>"
        "<tr><td>2. second</td><td>beta prose</td></tr></table>"
    )
    assert grid is not None
    assert is_false_grid(grid) is True
    assert unwrap_grid(grid) == "1. first alpha prose\n2. second beta prose"
