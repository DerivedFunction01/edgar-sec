"""End-to-end render tests for the ASCII table renderer.

`engine.tables.ascii_html` was dead for its entire lifetime: five of its modules
imported names that did not exist, and no test imported the package, so 1,248
green tests never noticed. This file renders a real table through the public
`SourceTable` seam so the package is proven load-bearing rather than merely
importable, and so a regression in any stage of the render pipeline is caught.
"""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html import convert_html_table
from edgar_sec.engine.tables.ascii_html.model import SourceCell, SourceTable
from edgar_sec.engine.tables.ascii_html.renderer import render_source_table


def _table(rows: list[list[str]]) -> SourceTable:
    cells = [
        tuple(
            SourceCell(row_index=r, source_col_index=c, tag="td", text=text)
            for c, text in enumerate(row)
        )
        for r, row in enumerate(rows)
    ]
    return SourceTable(table_index=0, rows=tuple(cells))


def test_renders_a_financial_table() -> None:
    result = render_source_table(
        _table(
            [
                ["Item", "2024", "2023"],
                ["Revenue", "$1,200", "$1,100"],
                ["Expenses", "(500)", "(400)"],
            ]
        )
    )

    assert result.ascii_text.strip(), "renderer produced no output"
    assert "$1,200" in result.ascii_text
    assert "$1,100" in result.ascii_text
    assert "(500)" in result.ascii_text
    assert "(400)" in result.ascii_text
    assert "Revenue" in result.ascii_text
    assert "Expenses" in result.ascii_text


def test_grid_preserves_row_and_column_count() -> None:
    result = render_source_table(
        _table(
            [
                ["Item", "2024", "2023"],
                ["Revenue", "$1,200", "$1,100"],
            ]
        )
    )

    assert len(result.resolved_grid.rows) == 2
    assert len(result.resolved_grid.column_widths) == 3
    assert len(result.resolved_grid.column_alignments) == 3


def test_numeric_columns_align_right() -> None:
    """Currency columns are right-aligned; a label column is not."""
    result = render_source_table(
        _table(
            [
                ["Item", "2024"],
                ["Revenue", "$1,200"],
            ]
        )
    )

    alignments = [a.name for a in result.resolved_grid.column_alignments]
    assert alignments[1] != alignments[0]


def test_range_marker_between_two_cells_survives_rendering() -> None:
    """`is_range_marker` was one of the dropped definitions; pin it end to end."""
    result = render_source_table(
        _table(
            [
                ["Item", "2024", "2023"],
                ["Revenue", "$1,200", "$1,100"],
                ["Change", "to", "$100"],
            ]
        )
    )

    assert "to" in result.ascii_text


def test_confidence_is_reported() -> None:
    result = render_source_table(_table([["A", "1"]]))

    assert 0.0 <= result.confidence <= 1.0


def test_empty_table_renders_without_raising() -> None:
    result = render_source_table(SourceTable(table_index=0))

    assert isinstance(result.ascii_text, str)


def test_convert_html_table_from_raw_html_string() -> None:
    """The HTML entry point: selectolax parses, the renderer lays out."""
    html = (
        "<table><tr><th>Item</th><th>2024</th></tr>"
        "<tr><td>Revenue</td><td>$1,200</td></tr>"
        "<tr><td>Expenses</td><td>(500)</td></tr></table>"
    )

    result = convert_html_table(html)

    assert result.ascii_text.strip()
    assert "$1,200" in result.ascii_text
    assert "(500)" in result.ascii_text
    assert "Revenue" in result.ascii_text
    assert len(result.resolved_grid.rows) == 3


def test_convert_html_table_handles_bytes_and_spans() -> None:
    html = (
        b'<table><tr><td>Income</td><td colspan="2">$900</td></tr>'
        b"<tr><td>Net</td><td>$300</td><td>$100</td></tr></table>"
    )

    result = convert_html_table(html)

    assert "$900" in result.ascii_text
    assert "$300" in result.ascii_text


def test_convert_html_table_of_empty_markup_is_not_a_crash() -> None:
    result = convert_html_table("<table></table>")

    assert isinstance(result.ascii_text, str)
