"""TableContext construction from successor-corpus records."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.context import TableContext
from tests.support import load_fixture


def _context(accession: str, table_index: int) -> TableContext:
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
    return TableContext.from_record(geometry, record)


def test_cooper_balance_sheet_context() -> None:
    context = _context("0000024491-19-000016", 6)
    assert context.table_index == 6
    assert context.caption_stack == (
        "COOPER TIRE & RUBBER COMPANY",
        "CONDENSED CONSOLIDATED BALANCE SHEETS",
        "(Dollar amounts in thousands except per share amounts)",
    )
    assert context.scale is not None and context.scale.unit == "thousands"
    assert context.location == (145, 186)
    assert context.section is not None
    assert context.section.item == "ITEM 1"
    assert context.section.title == "FINANCIAL STATEMENTS"
    assert context.note is None
    assert context.label is not None
    assert context.label.family == "balance_sheet"
    assert context.label.split == "derivation"
    assert context.breaks.before is not None
    assert context.breaks.before.namespace == "arabic"
    assert context.breaks.before.page_number == 3


def test_cooper_eps_context_carries_note() -> None:
    context = _context("0000024491-19-000016", 11)
    assert context.note is not None
    assert context.note.number == 1
    assert context.note.title == "Basis of Presentation and Consolidation"
    assert context.label is not None
    assert context.label.family == "eps_reconciliation"


def test_sothebys_balance_sheet_context() -> None:
    context = _context("0000823094-19-000029", 9)
    assert context.location == (198, 268)
    assert context.label is not None
    assert context.label.family == "balance_sheet"
    assert context.section is not None
    assert context.section.item == "ITEM 1"


def test_unlabelled_geometry_keeps_explicit_absence() -> None:
    context = _context("0000726854-20-000044", 6)
    assert context.label is None


def test_region_is_absent_unless_a_builder_stamps_it() -> None:
    context = _context("0000726854-20-000044", 6)
    assert context.region is None


def test_stamped_region_round_trips_from_record() -> None:
    filing = load_fixture("table_extraction_corpus/0000726854-20-000044.json")
    record = next(item for item in filing["geometries"] if item["table_index"] == 6)
    geometry = TableGeometry(
        table_index=6,
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
    stamped = TableContext.from_record(geometry, {**record, "region": "signature"})
    assert stamped.region == "signature"
