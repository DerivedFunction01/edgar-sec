"""EPS seat kind: the priced rule's specimen shapes.
Pins transcribe the depth-3 run's priced leg definitions.
"""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.context import TableContext
from edgar_sec.engine.tables.extraction.eps_evidence import EpsText, legs_for
from edgar_sec.engine.tables.extraction.eps_specs import EPS_EVIDENCE_SPECS
from edgar_sec.engine.tables.extraction.form_tests import evaluate_form_tests
from edgar_sec.engine.tables.extraction.typed_rows import TypedTable, structure_table

TEST_ID = "eps_evidence"
SPEC = EPS_EVIDENCE_SPECS["eps_reconciliation"]


def _table(
    rows: tuple[tuple[str, ...], ...],
    *,
    caption_stack: tuple[str, ...] = (),
    prose_before: str = "",
) -> TypedTable:
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
    context = TableContext(
        geometry=geometry, caption_stack=caption_stack, prose_before=prose_before
    )
    return structure_table(context)


def _outcome(table: TypedTable):
    return next(o for o in evaluate_form_tests(table) if o.test_id == TEST_ID)


def _legs(table: TypedTable):
    return legs_for(EpsText.from_table(table), SPEC)


def test_pair_form_seats_with_detector_silent() -> None:
    table = _table(
        (
            ("Basic earnings per share", "1.00"),
            ("Diluted earnings per share", "0.90"),
        ),
        prose_before="Net income per share — basic and diluted — follows.",
    )
    legs = _legs(table)
    assert legs.pair and legs.h1 and not legs.det
    outcome = _outcome(table)
    assert outcome.passed
    assert outcome.detail == "pair form, detector silent"


def test_denominator_identity_seats_without_the_pair() -> None:
    table = _table(
        (
            ("Basic shares", "10,000", "9,000"),
            ("Dilutive effect of options", "500", "400"),
            ("Diluted shares", "10,500", "9,400"),
        ),
        prose_before="Shares outstanding data follows.",
    )
    legs = _legs(table)
    assert legs.es_add and legs.bd_arm and not legs.pair
    outcome = _outcome(table)
    assert outcome.passed
    assert outcome.detail == "denominator form, detector silent"


def test_bridge_form_seats_without_basic_vocabulary() -> None:
    # The depth-2 :24 shape: a weighted-average bridge whose
    # stubs never say "basic", claimed by the W legs alone.
    table = _table(
        (
            ("Weighted average shares outstanding", "24,322,264", "20,000,000"),
            ("Dilutive effect of stock plans", "257,126", "100,000"),
            ("Diluted weighted average shares outstanding", "24,579,390", "20,100,000"),
        )
    )
    legs = _legs(table)
    assert legs.w_any and not legs.basic_diluted and not legs.det
    outcome = _outcome(table)
    assert outcome.passed
    assert outcome.detail == "bridge form, detector silent"


def test_combined_basic_and_diluted_row_seats_via_v_comb() -> None:
    table = _table((("Basic and diluted shares outstanding", "50,417", "49,315"),))
    legs = _legs(table)
    assert legs.v_comb and legs.v_any and legs.bd_arm
    assert _outcome(table).passed


def test_zero_effect_equality_seats_via_v_eq() -> None:
    # The depth-2 EQ class: basic and diluted denominators
    # equal, the anti-dilutive presentation.
    table = _table(
        (
            ("Basic shares", "713", "100"),
            ("Diluted shares", "713", "100"),
        )
    )
    legs = _legs(table)
    assert legs.v_eq and legs.v_eqx and not legs.es_add
    assert _outcome(table).passed


def test_operating_walk_grid_is_screened_by_det_walk3() -> None:
    # The depth-3 FP shape: an income-statement walk whose
    # per-share foot the pair reaches; the detector screens it.
    table = _table(
        (
            ("Revenue", "100"),
            ("Cost of revenue", "40"),
            ("Gross profit", "60"),
            ("Basic earnings per share", "1.00"),
            ("Diluted earnings per share", "0.90"),
        ),
        prose_before="Earnings per share — basic and diluted — are computed.",
    )
    legs = _legs(table)
    assert legs.pair and legs.h1 and legs.det_walk3 and legs.det
    outcome = _outcome(table)
    assert not outcome.passed
    assert outcome.detail == "detector screens the union form"


def test_terminal_per_share_foot_is_screened_by_det_foot60() -> None:
    table = _table(
        (
            ("Widgets", "10"),
            ("Gadgets", "20"),
            ("Gizmos", "30"),
            ("Basic per share", "1.0"),
            ("Diluted per share", "0.9"),
        ),
        prose_before="Per share amounts — basic and diluted — follow.",
    )
    legs = _legs(table)
    assert legs.pair and legs.det_foot60 and not legs.det_walk3
    assert legs.anatomy_first_fraction == 0.6
    assert not _outcome(table).passed


def test_statement_title_in_the_lead_is_screened_by_det_title() -> None:
    table = _table(
        (
            ("Basic shares", "10,000", "9,000"),
            ("Diluted shares", "10,500", "9,400"),
        ),
        prose_before="The statements of operations include basic and diluted amounts.",
    )
    legs = _legs(table)
    assert legs.pair and legs.det_title and not legs.det_walk3
    assert not _outcome(table).passed


def test_plain_grid_without_vocabulary_has_no_seat_leg() -> None:
    table = _table((("Apples", "10"), ("Oranges", "20")))
    legs = _legs(table)
    assert not legs.h1 and not legs.det and not legs.claim
    outcome = _outcome(table)
    assert not outcome.passed
    assert outcome.detail == "no seat leg"


def test_outcome_carries_the_seat_kind_and_points() -> None:
    outcome = _outcome(
        _table(
            (
                ("Basic earnings per share", "1.00"),
                ("Diluted earnings per share", "0.90"),
            ),
            prose_before="Net income per share — basic and diluted — follows.",
        )
    )
    assert outcome.family == "eps_reconciliation"
    assert outcome.kind == "eps_evidence"
    assert outcome.points == 3.0
    assert outcome.evaluable


def test_spec_carries_the_priced_thresholds() -> None:
    assert SPEC.foot_threshold == 60
    assert SPEC.walk_min_rows == 3
    assert SPEC.lead_term == "basic and"


def test_empty_grid_is_unevaluable() -> None:
    outcome = _outcome(_table(()))
    assert not outcome.passed
    assert not outcome.evaluable
    assert outcome.detail == "no grid rows"
