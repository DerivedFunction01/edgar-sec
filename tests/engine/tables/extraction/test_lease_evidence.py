"""Lease seat kind: the priced rule's specimen shapes.
Pins transcribe the depth-4 run's priced leg definitions.
"""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.context import TableContext
from edgar_sec.engine.tables.extraction.form_tests import evaluate_form_tests
from edgar_sec.engine.tables.extraction.lease_evidence import LeaseText, legs_for
from edgar_sec.engine.tables.extraction.lease_specs import LEASE_EVIDENCE_SPECS
from edgar_sec.engine.tables.extraction.typed_rows import TypedTable, structure_table

TEST_ID = "lease_evidence"
SPEC = LEASE_EVIDENCE_SPECS["lease_maturity"]

LADDER = (
    ("2012", "10"),
    ("2013", "10"),
    ("2014", "10"),
    ("2015", "10"),
    ("2016", "10"),
    ("Thereafter", "10"),
    ("Total", "60"),
)


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
    return legs_for(LeaseText.from_table(table), SPEC)


def test_core_ladder_with_total_line_seats_as_winner() -> None:
    table = _table(LADDER[:-1] + (("Total lease payments", "60"),))
    legs = _legs(table)
    assert legs.ladder3 and legs.total_pay and legs.core
    outcome = _outcome(table)
    assert outcome.passed
    assert outcome.detail == "winner: core or present-value form"


def test_present_value_stub_seats_as_winner_without_core() -> None:
    table = _table(
        (
            ("Minimum lease payments", "100"),
            ("Present value of minimum lease payments", "90"),
        )
    )
    legs = _legs(table)
    assert legs.pv_leg and not legs.core
    assert _outcome(table).passed


def test_stub_ladder_gold_shape_seats_under_the_class_guard() -> None:
    # The recovered stub-ladder golds: a complete ladder
    # failing CORE on the total line alone, seated by the
    # named form when the lead carries the class trio.
    table = _table(
        LADDER,
        prose_before="A schedule of rentals under operating leases follows.",
    )
    legs = _legs(table)
    assert legs.ladder3 and not legs.total_pay and not legs.winner
    assert legs.named and legs.prose_class_lead and legs.named_class
    outcome = _outcome(table)
    assert outcome.passed
    assert outcome.detail == "named ladder under the class guard"


def test_class_trio_on_the_caption_seats_the_named_form() -> None:
    table = _table(LADDER, caption_stack=("Operating lease commitments",))
    legs = _legs(table)
    assert legs.prose_class_cap and not legs.prose_class_lead
    assert _outcome(table).passed


def test_hyphenated_class_wording_matches_after_normalization() -> None:
    table = _table(
        LADDER,
        prose_before="The company holds equipment under capital-lease terms.",
    )
    legs = _legs(table)
    assert legs.prose_class_lead and legs.named_class
    assert _outcome(table).passed


def test_named_form_without_class_wording_fails() -> None:
    table = _table(
        LADDER,
        prose_before="The following table presents minimum rental payments.",
    )
    legs = _legs(table)
    assert legs.named and not legs.prose_class and not legs.claim
    outcome = _outcome(table)
    assert not outcome.passed
    assert outcome.detail == "no seat leg (year labels 5)"


def test_incidental_class_lead_on_a_debt_ladder_is_the_priced_fp() -> None:
    # The depth-4 FP :40 shape: a notes-payable maturity
    # ladder whose lead names capital leases incidentally;
    # the seat admits it, exactly as priced.
    table = _table(
        (
            ("2025", "10"),
            ("2026", "10"),
            ("Thereafter", "10"),
            ("Total notes payable", "30"),
        ),
        prose_before="Notes payable and capital leases are due as follows.",
    )
    legs = _legs(table)
    assert legs.named_class and not legs.winner
    assert _outcome(table).passed


def test_ladder_needs_two_distinct_year_labels() -> None:
    table = _table(
        (
            ("2013", "10"),
            ("2013", "20"),
            ("Thereafter", "10"),
        ),
        prose_before="Rentals under operating leases follow.",
    )
    legs = _legs(table)
    assert legs.year_labels == 1 and not legs.ladder2 and not legs.claim
    assert not _outcome(table).passed


def test_thereafter_must_open_the_stub() -> None:
    table = _table(
        (
            ("2013", "10"),
            ("2014", "10"),
            ("Due thereafter", "10"),
        ),
        prose_before="Rentals under operating leases follow.",
    )
    legs = _legs(table)
    assert legs.ladder2 and not legs.ta_row and not legs.named
    assert not _outcome(table).passed


def test_outcome_carries_the_seat_kind_and_points() -> None:
    outcome = _outcome(_table(LADDER[:-1] + (("Total lease payments", "60"),)))
    assert outcome.family == "lease_maturity"
    assert outcome.kind == "lease_evidence"
    assert outcome.points == 3.0
    assert outcome.evaluable


def test_empty_grid_is_unevaluable() -> None:
    outcome = _outcome(_table(()))
    assert not outcome.passed
    assert not outcome.evaluable
    assert outcome.detail == "no grid rows"
