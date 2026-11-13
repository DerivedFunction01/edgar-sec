"""Typed-row structuring pinned on the study's named specimens."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.context import TableContext
from edgar_sec.engine.tables.extraction.typed_rows import (
    RowKind,
    TypedTable,
    structure_table,
)
from tests.support import load_fixture


def _table(accession: str, table_index: int) -> TypedTable:
    filing = load_fixture(f"table_extraction_corpus/{accession}.json")
    record = next(
        item for item in filing["geometries"] if item["table_index"] == table_index
    )
    geometry = TableGeometry(
        table_index=table_index,
        render_result=TableRenderResult(
            ascii_text="",
            resolved_grid=ResolvedGrid(
                rows=tuple(tuple(row) for row in record["rows"]),
                column_alignments=(),
                column_widths=(),
                header_row_count=record["header_row_count"],
            ),
            confidence=1.0,
        ),
    )
    return structure_table(TableContext.from_record(geometry, record))


def _period_labels(table: TypedTable) -> tuple[str | None, ...]:
    return tuple(period.label for period in table.periods)


def _row(table: TypedTable, label: str):
    return next(row for row in table.rows if row.label == label)


def test_cooper_income_caption_and_period_stack() -> None:
    table = _table("0000024491-19-000016", 4)
    assert table.caption.company == "COOPER TIRE & RUBBER COMPANY"
    assert table.caption.titles == ("CONDENSED CONSOLIDATED STATEMENTS OF INCOME",)
    assert table.caption.audit_status == "unaudited"
    assert table.scale is not None and table.scale.unit == "thousands"
    assert _period_labels(table) == (
        "Three Months Ended March 31, 2019",
        "Three Months Ended March 31, 2018",
    )
    net_sales = _row(table, "Net sales")
    assert net_sales.values == (619163, 601496)
    assert net_sales.kind is RowKind.DATA
    assert _row(table, "Gross profit").values == (88259, 84485)


def test_cooper_balance_sheet_split_parts() -> None:
    assets = _table("0000024491-19-000016", 6)
    liabilities = _table("0000024491-19-000016", 7)
    assert _period_labels(assets) == (
        "March 31, 2019 (Unaudited)",
        "December 31, 2018",
    )
    assert _row(assets, "ASSETS").kind is RowKind.SECTION
    assert _row(assets, "Cash and cash equivalents").values == (212331, 356254)
    assert assets.continued is False
    assert liabilities.continued is True
    assert liabilities.caption.titles == assets.caption.titles
    assert _row(liabilities, "LIABILITIES AND EQUITY").kind is RowKind.SECTION
    assert _row(liabilities, "Notes payable").values == (20074, 15288)


def test_cooper_cash_flow_sections() -> None:
    table = _table("0000024491-19-000016", 8)
    assert _period_labels(table) == (
        "Three Months Ended March 31, 2019",
        "Three Months Ended March 31, 2018",
    )
    assert _row(table, "Operating activities:").kind is RowKind.SECTION
    assert _row(table, "Net income").values == (7178, 8983)


def test_cooper_eps_header_scale_and_periods() -> None:
    table = _table("0000024491-19-000016", 11)
    assert table.scale is not None and table.scale.unit == "thousands"
    assert _period_labels(table) == (
        "Three Months Ended March 31, 2019",
        "Three Months Ended March 31, 2018",
    )
    assert _row(table, "Numerator").kind is RowKind.SECTION
    assert _row(table, "Denominator").kind is RowKind.SECTION


def test_tutor_perini_income_three_year_stack() -> None:
    table = _table("0000077543-25-000025", 27)
    assert table.scale is not None and table.scale.unit == "thousands"
    assert _period_labels(table) == (
        "Year Ended December 31, 2024",
        "Year Ended December 31, 2023",
        "Year Ended December 31, 2022",
    )
    assert _row(table, "REVENUE").values == (4326922, 3880227, 3790755)
    assert _row(table, "COST OF OPERATIONS").values == (
        -4129884,
        -3739603,
        -3761143,
    )


def test_tutor_perini_balance_sheet_as_of() -> None:
    table = _table("0000077543-25-000025", 29)
    assert _period_labels(table) == (
        "As of December 31, 2024",
        "As of December 31, 2023",
    )
    assert _row(table, "ASSETS").kind is RowKind.SECTION
    assert _row(table, "Restricted cash").values == (9104, 14116)


def test_sothebys_income_two_period_groups() -> None:
    table = _table("0000823094-19-000029", 7)
    assert _period_labels(table) == (
        "Three Months Ended June 30, 2019",
        "Three Months Ended June 30, 2018",
        "Six Months Ended June 30, 2019",
        "Six Months Ended June 30, 2018",
    )
    assert _row(table, "Revenues:").kind is RowKind.SECTION
    total = _row(table, "Total revenues")
    assert total.kind is RowKind.TOTAL
    assert total.values == (361778, 345636, 535243, 541432)


def test_sothebys_balance_sheet_merged_caption_cell() -> None:
    table = _table("0000823094-19-000029", 9)
    assert table.caption.audit_status == "unaudited"
    assert table.scale is not None and table.scale.unit == "thousands"
    assert any("BALANCE SHEETS" in title for title in table.caption.titles)
    assert _period_labels(table) == (
        "June 30, 2019",
        "December 31, 2018",
        "June 30, 2018",
    )
    assert _row(table, "A S S E T S").kind is RowKind.SECTION
    assert _row(table, "Cash and cash equivalents").values == (
        132137,
        178579,
        432357,
    )
