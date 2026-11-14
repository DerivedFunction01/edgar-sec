"""Residue families: note titles assign only corroborated grids."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.classify import classify_table
from edgar_sec.engine.tables.extraction.competition import GeometryText
from edgar_sec.engine.tables.extraction.context import NoteRef, TableContext
from edgar_sec.engine.tables.extraction.residue_families import (
    content_score,
    corroborates,
    segment_grid,
)
from edgar_sec.engine.tables.extraction.typed_rows import structure_table


def _table(rows: tuple[tuple[str, ...], ...], note_title: str) -> object:
    geometry = TableGeometry(
        table_index=0,
        render_result=TableRenderResult(
            ascii_text="",
            resolved_grid=ResolvedGrid(
                rows=rows, column_alignments=(), column_widths=(), header_row_count=0
            ),
            confidence=1.0,
        ),
    )
    context = TableContext(geometry=geometry, note=NoteRef(7, None, note_title))
    return structure_table(context)


def test_segment_grid_needs_measures_not_title() -> None:
    grid = GeometryText(
        stubs=("segment revenue", "total segment revenue", "corporate and other")
    )
    assert segment_grid(grid)
    titled = GeometryText(stubs=("apples", "oranges"))
    assert not segment_grid(titled)


def test_content_score_counts_distinct_terms() -> None:
    grid = GeometryText(
        stubs=("loss contingencies", "litigation accrual", "letters of credit")
    )
    assert content_score("commitments_contingencies", grid) >= 2
    assert corroborates("commitments_contingencies", grid)


def test_title_alone_does_not_corroborate() -> None:
    grid = GeometryText(stubs=("cash", "receivables", "inventory"))
    assert not corroborates("related_party", grid)
    assert not corroborates("commitments_contingencies", grid)


def test_note_claim_assigns_corroborated_segment_grid() -> None:
    rows = (
        ("Segment revenue", "100"),
        ("Total segment revenue", "100"),
        ("Corporate and other", "5"),
    )
    result = classify_table(_table(rows, "Segment Information"))  # type: ignore[arg-type]
    assert result.family == "segment_reporting"


def test_note_claim_refuses_uncorroborated_sibling_grid() -> None:
    rows = (
        ("Cash and cash equivalents", "100"),
        ("Accounts receivable", "50"),
        ("Inventories", "25"),
    )
    result = classify_table(_table(rows, "Segment Information"))  # type: ignore[arg-type]
    assert result.family != "segment_reporting"
