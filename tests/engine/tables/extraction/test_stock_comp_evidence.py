"""Stock comp evidence seat: registry data, specimen shapes."""

from __future__ import annotations

from dataclasses import replace

from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.context import TableContext
from edgar_sec.engine.tables.extraction.form_test_specs import FORM_TEST_SPECS
from edgar_sec.engine.tables.extraction.form_tests import evaluate_form_tests
from edgar_sec.engine.tables.extraction.profiles import (
    FORM_TESTS,
    PROV_R18_SEAT_PRICING,
    TEST_STOCK_COMP_EVIDENCE,
    profile_for,
)
from edgar_sec.engine.tables.extraction.stock_comp_evidence import (
    StockCompText,
    evaluate_stock_comp,
    legs_for,
)
from edgar_sec.engine.tables.extraction.stock_comp_specs import (
    STOCK_COMP_EVIDENCE_SPECS,
    STOCK_COMP_EVIDENCE_SPECS_BY_TEST_ID,
)
from edgar_sec.engine.tables.extraction.typed_rows import structure_table

SPEC = STOCK_COMP_EVIDENCE_SPECS["stock_comp_rollforward"]
SEAT = replace(SPEC, claim_form="seat")
DERIVED = replace(SPEC, claim_form="derived")


def _text(rows, lead=""):
    return StockCompText(rows=tuple(tuple(r) for r in rows), lead=lead)


def _table(rows, prose_before=""):
    geometry = TableGeometry(
        table_index=0,
        render_result=TableRenderResult(
            ascii_text="",
            resolved_grid=ResolvedGrid(
                rows=tuple(tuple(r) for r in rows),
                column_alignments=(),
                column_widths=(),
                header_row_count=0,
            ),
            confidence=1.0,
        ),
    )
    context = TableContext(geometry=geometry, prose_before=prose_before)
    return structure_table(context)


PAIR_ROWS = (
    ("Balance at beginning of year", "100"),
    ("Granted", "50"),
    ("Exercised", "(20)"),
    ("Balance at end of year", "130"),
)

EMDASH_ROWS = (
    (
        "Range of Exercise Prices",
        "Options Outstanding",
        "Weighted Average Exercise Price",
        "Options Exercisable",
    ),
    ("$0.00—3.00", "1,000", "1.50", "900"),
    ("$3.01—5.00", "2,000", "4.00", "1,800"),
    ("$5.01—10.00", "3,000", "7.50", "2,700"),
)

HYPHEN_ROWS = (
    (
        "Range of Exercise Prices",
        "Shares Outstanding",
        "Weighted-Average Exercise Price",
    ),
    ("$1.00 - $2.00", "500", "1.50"),
    ("$2.01 - $3.00", "600", "2.50"),
)

NO_GRANTS_ROWS = (
    ("Outstanding at beginning of year", "100"),
    ("Exercised", "(50)"),
    ("Forfeited", "(10)"),
    ("Outstanding at end of year", "40"),
)

PROXY_ROWS = (
    ("", "Shares Under Option", "Exercisable"),
    ("Outstanding at beginning of year", "100", "80"),
    ("Granted", "50", "0"),
    ("Exercised", "(20)", "(20)"),
    ("Outstanding at end of year", "130", "60"),
)

LLC_ROWS = (
    ("Unvested at beginning of year", "100"),
    ("Issued", "50"),
    ("Vested", "(30)"),
    ("Unvested at end of year", "120"),
)


def test_seat_is_declared_as_form_test_data():
    spec = next(s for s in FORM_TEST_SPECS if s.test_id == "stock_comp_evidence")
    assert spec.family == "stock_comp_rollforward"
    assert spec.kind == TEST_STOCK_COMP_EVIDENCE
    assert spec.points == 3.0
    assert spec.provenance == PROV_R18_SEAT_PRICING
    assert TEST_STOCK_COMP_EVIDENCE in FORM_TESTS
    assert TEST_STOCK_COMP_EVIDENCE in profile_for("stock_comp_rollforward").form_tests
    assert STOCK_COMP_EVIDENCE_SPECS_BY_TEST_ID["stock_comp_evidence"] is SPEC


def test_pair_leg_seats_the_claim():
    legs = legs_for(_text(PAIR_ROWS), SPEC)
    assert legs.pair and not legs.gx2
    verdict = evaluate_stock_comp(_text(PAIR_ROWS), SEAT)
    assert verdict.admitted and "pair" in verdict.detail


def test_gx2_seats_on_the_emdash_price_form():
    legs = legs_for(_text(EMDASH_ROWS), SPEC)
    assert legs.gx2 and legs.range_rows == 3
    assert legs.col_waep and legs.col_out and legs.col_exerc
    assert not legs.pair
    assert evaluate_stock_comp(_text(EMDASH_ROWS), SEAT).admitted
    assert not evaluate_stock_comp(_text(EMDASH_ROWS), DERIVED).admitted


def test_gx2_seats_on_the_hyphen_price_form():
    legs = legs_for(_text(HYPHEN_ROWS), SPEC)
    assert legs.gx2 and legs.range_rows == 2
    assert evaluate_stock_comp(_text(HYPHEN_ROWS), SEAT).admitted


def test_gx2_needs_two_range_rows():
    rows = (
        EMDASH_ROWS[0],
        ("$0.00—3.00", "1,000", "1.50", "900"),
        ("Total", "1,000", "1.50", "900"),
    )
    legs = legs_for(_text(rows), SPEC)
    assert legs.range_rows == 1 and not legs.gx2
    assert not evaluate_stock_comp(_text(rows), SEAT).admitted


def test_gx2_needs_the_waep_column():
    rows = (
        ("Range of Exercise Prices", "Options Outstanding", "Remaining Life"),
        ("$0.00—3.00", "1,000", "5.0"),
        ("$3.01—5.00", "2,000", "4.0"),
    )
    legs = legs_for(_text(rows), SPEC)
    assert not legs.col_waep and not legs.gx2


def test_gx2_needs_an_outstanding_or_exercisable_column():
    rows = (
        (
            "Range of Exercise Prices",
            "Number of Shares",
            "Weighted Average Exercise Price",
        ),
        ("$0.00—3.00", "1,000", "1.50"),
        ("$3.01—5.00", "2,000", "4.00"),
    )
    legs = legs_for(_text(rows), SPEC)
    assert legs.col_waep and not legs.col_out and not legs.col_exerc
    assert not legs.gx2


def test_no_grants_rollforward_is_the_seat_forms_priced_miss():
    text = _text(NO_GRANTS_ROWS, lead="Stock options outstanding and activity:")
    legs = legs_for(text, SPEC)
    assert legs.winner and not legs.pair and not legs.gx2
    assert not evaluate_stock_comp(text, SEAT).admitted
    assert evaluate_stock_comp(text, DERIVED).admitted


def test_exercisable_column_fences_the_derived_winner_only():
    legs = legs_for(_text(PROXY_ROWS), SPEC)
    assert legs.pair and legs.col_exerc
    assert evaluate_stock_comp(_text(PROXY_ROWS), SEAT).admitted
    assert not evaluate_stock_comp(_text(PROXY_ROWS), DERIVED).admitted


def test_units_lead_with_typed_core_seats_the_derived_form():
    text = _text(
        LLC_ROWS,
        lead="Activity for the company's restricted stock units:",
    )
    legs = legs_for(text, SPEC)
    assert legs.units_lead and legs.core and not legs.pair
    assert not evaluate_stock_comp(text, SEAT).admitted
    assert evaluate_stock_comp(text, DERIVED).admitted


def test_a_single_activity_row_never_pairs():
    rows = (
        ("Granted", "50"),
        ("Balance at end of year", "50"),
    )
    legs = legs_for(_text(rows), SPEC)
    assert legs.activity_rows == 1 and not legs.act2 and not legs.pair
    assert not evaluate_stock_comp(_text(rows), SEAT).admitted
    assert not evaluate_stock_comp(_text(rows), DERIVED).admitted


def test_non_family_stubs_fire_no_leg():
    rows = (
        ("Cash and cash equivalents", "100"),
        ("Accounts receivable", "50"),
        ("Total assets", "150"),
    )
    legs = legs_for(_text(rows), SPEC)
    assert not legs.pair and not legs.gx2 and not legs.winner
    assert not legs.core and not legs.seat_claim and not legs.derived_claim


def test_adapter_outcome_matches_the_shipped_claim_form():
    spec = next(s for s in FORM_TEST_SPECS if s.test_id == "stock_comp_evidence")
    for rows in (PAIR_ROWS, EMDASH_ROWS, NO_GRANTS_ROWS):
        outcomes = evaluate_form_tests(_table(rows), specs=(spec,))
        outcome = next(o for o in outcomes if o.kind == TEST_STOCK_COMP_EVIDENCE)
        legs = legs_for(_text(rows), SPEC)
        assert outcome.passed == legs.claim(SPEC.claim_form)
        assert outcome.evaluable and outcome.points == 3.0
