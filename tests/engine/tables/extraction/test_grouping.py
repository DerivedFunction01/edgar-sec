"""Grouping signatures over synthetic grids."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.context import TableContext
from edgar_sec.engine.tables.extraction.grouping import (
    grouping_signatures,
    has_balance_pair,
    header_components,
    movement_row_count,
)
from edgar_sec.engine.tables.extraction.typed_rows import structure_table

_EQUITY_ROWS = (
    ("Consolidated Statements of Changes in Stockholders' Equity",),
    (
        "",
        "Common Stock",
        "",
        "Retained",
        "",
        "Accumulated Other Comprehensive",
        "",
        "Total Shareholders’",
    ),
    ("", "Shares", "", "Earnings", "", "Income (Loss)", "", "Equity"),
    ("Balance at December 31, 2023", "", "100", "", "500", "", "5", "605"),
    ("Net income", "", "", "", "50", "", "", "50"),
    ("Other comprehensive loss", "", "", "", "", "", "(5)", "(5)"),
    ("Dividends declared", "", "", "", "(20)", "", "", "(20)"),
    ("Issuance of common stock", "", "10", "", "", "", "", "10"),
    ("Repurchase of common stock", "", "(2)", "", "", "", "", "(2)"),
    ("Balance at December 31, 2024", "", "108", "", "530", "", "0", "638"),
)

_BALANCE_ROWS = (
    ("Consolidated Balance Sheets",),
    ("", "December 31, 2024", "December 31, 2023"),
    ("Cash and cash equivalents", "100", "90"),
    ("Total assets", "100", "90"),
    ("Total stockholders' equity", "60", "55"),
)

_PARTIAL_ROWS = (
    ("Share Activity",),
    ("", "Common Stock", "", "Paid-in Capital"),
    ("Balance at January 1, 2024", "100", "", "500"),
    ("Issuance of common stock", "10", "", "50"),
    ("Repurchase of common stock", "(2)", "", "(20)"),
    ("Stock-based compensation", "", "", "30"),
    ("Net income", "", "", "40"),
    ("Balance at December 31, 2024", "108", "", "600"),
)


def _table(rows: tuple[tuple[str, ...], ...]):
    geometry = TableGeometry(
        table_index=0,
        render_result=TableRenderResult(
            ascii_text="",
            resolved_grid=ResolvedGrid(
                rows=rows,
                column_alignments=(),
                column_widths=(),
                header_row_count=0,
            ),
            confidence=1.0,
        ),
    )
    return structure_table(TableContext(geometry=geometry))


def test_equity_grid_fires_every_signature() -> None:
    table = _table(_EQUITY_ROWS)
    assert header_components(table) == {
        "common_stock",
        "retained",
        "aoci",
        "total_equity",
    }
    assert has_balance_pair(table)
    assert movement_row_count(table) >= 4
    assert grouping_signatures(table) == {
        "component_columns",
        "rollforward_grid",
        "movement_grid",
        "complete_grid",
    }


def test_balance_sheet_grid_fires_nothing() -> None:
    table = _table(_BALANCE_ROWS)
    assert header_components(table) == frozenset()
    assert grouping_signatures(table) == frozenset()


def test_two_component_grid_fires_movement_only() -> None:
    table = _table(_PARTIAL_ROWS)
    assert grouping_signatures(table) == {"movement_grid"}
