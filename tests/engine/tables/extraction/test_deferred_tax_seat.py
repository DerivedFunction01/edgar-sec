"""Deferred tax seat: the maximal join's priced shapes."""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.classify import classify_filing
from edgar_sec.engine.tables.extraction.context import TableContext
from edgar_sec.engine.tables.extraction.deferred_tax_seat import (
    SEAT_DETAIL_PREFIX,
    legs_for,
    seat_claims,
    text_from_table,
)
from edgar_sec.engine.tables.extraction.typed_rows import TypedTable, structure_table

_TWO_SIDED = (
    ("", "2023", "2024"),
    ("Deferred tax assets:", "", ""),
    ("Net operating loss carryforwards", "100", "90"),
    ("Tax credit carryforwards", "50", "40"),
    ("Total deferred tax assets", "150", "130"),
    ("Less: valuation allowance", "(10)", "(10)"),
    ("Net deferred tax assets", "140", "120"),
    ("Deferred tax liabilities:", "", ""),
    ("Depreciation", "60", "55"),
    ("Total deferred tax liabilities", "60", "55"),
)
_COMPANION = (
    ("Other current assets", "500"),
    ("Deferred income taxes", "1,087"),
    ("Total deferred tax liabilities", "1,008"),
)
_NO_CLOSING = (
    ("Deferred income taxes", "200"),
    ("Other current assets", "500"),
)
_WALK = (
    ("Deferred federal and state income taxes:", ""),
    ("Balance, January 1", "100"),
    ("Change in valuation allowance", "5"),
    ("Balance, December 31", "105"),
)


def _table(rows: tuple[tuple[str, ...], ...]) -> TypedTable:
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
    return structure_table(TableContext(geometry=geometry))


def test_two_sided_composition_seats_as_base() -> None:
    claims = seat_claims([_table(_TWO_SIDED)], ["pension"])
    assert claims[0].startswith(f"{SEAT_DETAIL_PREFIX} base")
    assert "CORE" in claims[0]


def test_primary_classification_blocks_the_base() -> None:
    table = _table(_TWO_SIDED)
    for family in ("balance_sheet", "income_statement", "cash_flow"):
        assert seat_claims([table], [family]) == {}


def test_valuation_allowance_walk_seats_as_base() -> None:
    rows = (
        ("Valuation allowance at beginning of period", "100"),
        ("Change in deferred tax asset positions", "5"),
        ("Valuation allowance at end of period", "105"),
    )
    claims = seat_claims([_table(rows)], ["other"])
    assert "A5" in claims[0]


def test_header_carried_arms_seat_as_base() -> None:
    rows = (
        ("Carryforwards", "Deferred Tax Assets", "Expires"),
        ("Net operating loss", "100", "2030"),
        ("Tax credits", "50", "2031"),
        ("", "150", ""),
    )
    legs = legs_for(text_from_table(_table(rows)))
    assert legs["A6b"] and not legs["CORE"]
    claims = seat_claims([_table(rows)], ["other"])
    assert "A6b" in claims[0]


def test_companion_joins_beside_a_base_claim() -> None:
    tables = [_table(_TWO_SIDED), _table(_COMPANION)]
    claims = seat_claims(tables, ["pension", "other"])
    assert claims[1] == f"{SEAT_DETAIL_PREFIX} companion"


def test_companion_needs_a_base_claim_in_the_filing() -> None:
    assert seat_claims([_table(_COMPANION)], ["other"]) == {}


def test_companion_needs_closing() -> None:
    tables = [_table(_TWO_SIDED), _table(_NO_CLOSING)]
    claims = seat_claims(tables, ["pension", "other"])
    assert 1 not in claims


def test_walk_arm_seats_without_the_clause() -> None:
    claims = seat_claims([_table(_WALK)], ["cash_flow"])
    assert claims[0] == f"{SEAT_DETAIL_PREFIX} a4va"


def test_plain_statement_grid_claims_nothing() -> None:
    rows = (
        ("Cash and cash equivalents", "100"),
        ("Accounts receivable", "50"),
        ("Total assets", "150"),
    )
    assert seat_claims([_table(rows)], ["other"]) == {}


def test_seat_act_rewrites_the_classification() -> None:
    results, _scores = classify_filing([_table(_TWO_SIDED)])
    result = results[0]
    assert result.family == "deferred_tax"
    assert result.tier == "seat"
    assert any(
        entry.group == "seat" and entry.detail.startswith(SEAT_DETAIL_PREFIX)
        for entry in result.evidence
    )
