"""Residue families: note titles assign only corroborated grids."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.cascade.scoring.classify import classify_table
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
    geometry_text_from_table,
)
from edgar_sec.engine.tables.extraction.core.text.context import NoteRef, TableContext
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    ClaimGroup,
    CompetitionResult,
)
from edgar_sec.engine.tables.extraction.cascade.residue_families import (
    content_score,
    corroborates,
    geographic_terms_present,
    segment_caption_name,
    segment_geographic_partition,
    segment_grid,
    segment_header_partition,
    segment_vocabulary,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table


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


def test_segment_grid_admits_segment_named_columns() -> None:
    grid = GeometryText(
        stubs=(
            "resident fees and services",
            "total revenues",
            "consolidated net operating income",
        ),
        grid_text=(
            "year ended seniors housing operating triple-net "
            "outpatient medical non-segment corporate total"
        ),
    )
    assert segment_grid(grid)


def test_segment_grid_admits_reconciliation_columns() -> None:
    grid = GeometryText(
        stubs=("interest income", "total revenues"),
        grid_text="retail banking mortgage banking eliminations consolidated",
    )
    assert segment_grid(grid)


def test_segment_grid_admits_section_row_segments() -> None:
    grid = GeometryText(
        stubs=(
            "general banking segment",
            "service charges on deposit accounts",
            "net interest income",
            "wealth management segment",
        )
    )
    assert segment_grid(grid)


def test_segment_grid_admits_disaggregation_leadin() -> None:
    grid = GeometryText(
        stubs=("medicare commissions", "pharmacy", "total senior revenue"),
        leadin="revenue disaggregated by reportable operating segment",
    )
    assert segment_grid(grid)


def test_segment_grid_admits_geographic_framing() -> None:
    grid = GeometryText(
        stubs=("puerto rico", "united states", "total consolidated revenues"),
        caption="geographic information",
        leadin="the company's reportable segments earn revenues worldwide",
    )
    assert segment_grid(grid)


def test_segment_grid_admits_place_vocabulary() -> None:
    # The measure sits in the framing only; the grid itself is a
    # place breakdown with a total. No older arm admits this: the
    # substrate place-vocabulary arm does.
    grid = GeometryText(
        stubs=("united states", "europe", "total"),
        leadin="segment revenues were as follows",
    )
    assert segment_grid(grid)


def test_segment_grid_refuses_place_vocabulary_without_total() -> None:
    grid = GeometryText(
        stubs=("united states", "europe", "revenues"),
        leadin="the company's segments",
    )
    assert not segment_grid(grid)


def test_geographic_terms_present_reads_the_grid_channel() -> None:
    grid = GeometryText(stubs=("united states", "europe", "total"))
    assert set(geographic_terms_present(grid)) >= {"united states", "europe"}


def test_segment_grid_admits_segment_measure_heading() -> None:
    grid = GeometryText(
        stubs=("direct", "retail", "total capital expenditures"),
        leadin="notes to financial statements segment capital expenditures",
    )
    assert segment_grid(grid)


def test_segment_grid_admits_intersegment_rows() -> None:
    grid = GeometryText(
        stubs=("motor fuel sales", "intersegment sales", "total revenue"),
        grid_text="fuel distribution all other eliminations totals",
    )
    assert segment_grid(grid)


def test_segment_grid_admits_segment_assets_columns() -> None:
    grid = GeometryText(
        stubs=(
            "total assets",
            "fluids division",
            "production testing division",
            "corporate overhead",
            "consolidated",
        )
    )
    assert segment_grid(grid)


def test_segment_grid_refuses_signature_block() -> None:
    grid = GeometryText(stubs=("by:", "president and chief executive officer", "date:"))
    assert not segment_grid(grid)


def test_segment_grid_refuses_measure_only_schedule() -> None:
    grid = GeometryText(
        stubs=("land", "building", "total", "less accumulated depreciation"),
        caption="schedule of capital leased assets",
    )
    assert not segment_grid(grid)


def test_segment_grid_refuses_expense_composition() -> None:
    grid = GeometryText(
        stubs=(
            "research and development",
            "selling general and administrative",
            "amortization of purchased intangible assets",
            "total",
        )
    )
    assert not segment_grid(grid)


def test_segment_grid_refuses_unframed_geography() -> None:
    grid = GeometryText(
        stubs=("taiwan", "china", "total revenues"),
        leadin="revenues by country were as follows",
    )
    assert not segment_grid(grid)


def test_segment_grid_refuses_prose_only_segment_mentions() -> None:
    grid = GeometryText(
        stubs=("cash and cash equivalents", "accounts receivable", "inventories"),
        leadin="our operating segments and reportable segments grew segment revenue",
    )
    assert not segment_grid(grid)


def test_grid_text_carries_header_cells() -> None:
    rows = (
        ("", "Year Ended December 31, 2020", "", ""),
        ("", "Refining", "Eliminations", "Consolidated"),
        ("Gasoline", "100", "0", "100"),
        ("Total revenues", "300", "0", "300"),
    )
    table = _table(rows, "Segment Information")
    text = geometry_text_from_table(table)  # type: ignore[arg-type]
    assert "eliminations" in text.grid_text
    assert segment_grid(text)


def test_note_claim_assigns_column_named_segment_grid() -> None:
    rows = (
        ("", "Year Ended December 31, 2020", "", ""),
        ("", "Refining", "Eliminations", "Consolidated"),
        ("Gasoline", "100", "0", "100"),
        ("Total revenues", "300", "0", "300"),
    )
    result = classify_table(_table(rows, "Segment Information"))  # type: ignore[arg-type]
    assert result.family == "segment_reporting"


def test_note_claim_refuses_expense_grid_in_segment_note() -> None:
    rows = (
        ("Research and development", "100"),
        ("Selling, general and administrative", "50"),
        ("Total", "150"),
    )
    result = classify_table(_table(rows, "Segment Information"))  # type: ignore[arg-type]
    assert result.family != "segment_reporting"


def test_header_partition_reads_a_total_column() -> None:
    grid = GeometryText(headers=("North America", "Europe", "Asia Pacific", "Total"))
    assert segment_header_partition(grid)


def test_header_partition_reads_a_consolidated_column() -> None:
    grid = GeometryText(headers=("Domestic", "Foreign", "Consolidated Total"))
    assert segment_header_partition(grid)


def test_header_partition_needs_three_non_period_headers() -> None:
    dated = GeometryText(headers=("2023", "2024", "Total"))
    assert not segment_header_partition(dated)
    worded = GeometryText(headers=("Three Months Ended", "Six Months Ended", "Total"))
    assert not segment_header_partition(worded)


def test_header_partition_needs_a_total_column() -> None:
    grid = GeometryText(headers=("North America", "Europe", "Asia Pacific", "Other"))
    assert not segment_header_partition(grid)


def test_geographic_partition_reads_places_closed_by_a_total() -> None:
    grid = GeometryText(stubs=("United States", "Canada", "Mexico", "Total"))
    assert segment_geographic_partition(grid)


def test_geographic_partition_needs_a_total_stub() -> None:
    grid = GeometryText(stubs=("United States", "Canada", "Mexico", "Other"))
    assert not segment_geographic_partition(grid)


def test_geographic_partition_needs_three_places() -> None:
    grid = GeometryText(stubs=("United States", "Canada", "Total"))
    assert not segment_geographic_partition(grid)


def _seg_result(state: str = "contested") -> CompetitionResult:
    group = ClaimGroup(
        family="segment_reporting",
        score=9.0,
        state=state,
        role="head",
        channels={},
        veto_flags=(),
        explained_foreign=0.0,
    )
    return CompetitionResult(
        claims=("segment_reporting",), contested=(), scores={}, groups=(group,)
    )


def test_segment_vocabulary_harvests_pre_seat_stub_names() -> None:
    grid = GeometryText(
        stubs=(
            "Commercial Banking",
            "Consumer and Small Business Banking",
            "Total revenues",
            "Segment income (in millions)",
            "Commercial Banking in millions",
            "Corporate and other",
            "Three months ended",
            "Banking 2024 results",
            "Banking",
        )
    )
    assert segment_vocabulary([grid], [_seg_result()]) == frozenset(
        {"commercial banking", "consumer and small business banking"}
    )


def test_segment_vocabulary_skips_seat_adds_and_unclaimed() -> None:
    grid = GeometryText(stubs=("Commercial Banking",))
    assert segment_vocabulary([grid], [_seg_result(state="reach")]) == frozenset()
    unclaimed = CompetitionResult(claims=(), contested=(), scores={})
    assert segment_vocabulary([grid], [unclaimed]) == frozenset()


def test_segment_caption_name_matches_on_word_boundaries() -> None:
    vocabulary = frozenset({"commercial banking"})
    assert segment_caption_name("TABLE 23: Commercial Banking", vocabulary)
    assert segment_caption_name(
        "Consumer and Small Business Banking | Commercial Banking",
        frozenset({"consumer and small business banking"}),
    )
    assert not segment_caption_name("Commercial Bankingx results", vocabulary)
    assert not segment_caption_name("commercial bank", vocabulary)
    assert not segment_caption_name("Commercial Banking", frozenset())
    assert not segment_caption_name("", vocabulary)
