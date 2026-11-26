"""Lease span seat: the priced formation seat for lease
ladders the chain leaves unclaimed.

Final compete_filing pass: an unclaimed geometry seats
lease_maturity on score, year span, and stub purity.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    ClaimGroup,
    CompetitionResult,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.note_separators.lease_separator_evidence import (
    debt_seat_claimed,
)
from edgar_sec.engine.tables.extraction.seats.seat_application import (
    seat_applier,
    seat_role,
)

FAMILY = "lease_maturity"

# Priced by the span-arm trace at its balanced point and the
# ladder-attribution composition: the debt-seat conjunct is
# part of the seat's as-built form, not a later guard.
SEAT_FLOOR = 15.0
SPAN_MIN = 4
PURITY_MIN = 0.7
# Priced on the enlarged set + corpus-wide (3,768 geometries):
# period steps >= 3 under the seat's other conditions converts
# exactly 3 short ladders at zero false cost; >= 4 converts none.
STEPS_MIN = 3
# Priced fragment arm: a short pure ladder (steps >= 2, ladder
# purity >= .99) seats at a relieved floor; corpus population
# is exactly 2 trues at zero false cost.
FRAGMENT_FLOOR = 8.0
FRAGMENT_STEPS_MIN = 2
FRAGMENT_PURITY_MIN = 0.99
# Priced transposed arm: a transposed period axis seats at 14;
# corpus population is exactly 1 true at zero false cost.
TRANSPOSED_FLOOR = 14.0


def _seat_one(geometry: GeometryText, result: CompetitionResult) -> CompetitionResult:
    """Seat lease_maturity on one unclaimed geometry, or don't."""
    if result.claims:
        return result
    if any(group.family == FAMILY for group in result.groups):
        return result
    score = result.scores.get(FAMILY)
    if score is None:
        return result
    if debt_seat_claimed(geometry.form_tests):
        return result
    purity_met = (
        geometry.stub_ladder_purity >= PURITY_MIN
        or geometry.period_purity >= PURITY_MIN
        or geometry.block_purity >= PURITY_MIN
    )
    main_form = (
        score.total >= SEAT_FLOOR
        and (geometry.year_span >= SPAN_MIN or geometry.period_steps >= STEPS_MIN)
        and purity_met
    )
    fragment_form = (
        score.total >= FRAGMENT_FLOOR
        and geometry.period_steps >= FRAGMENT_STEPS_MIN
        and geometry.stub_ladder_purity >= FRAGMENT_PURITY_MIN
    )
    # Priced block arm: a short ladder whose block is pure seats
    # at the standing floor when it carries two period steps, or
    # one step over a two-year span; corpus population is
    # exactly 8 trues at zero false cost.
    block_form = (
        score.total >= SEAT_FLOOR
        and geometry.block_purity >= PURITY_MIN
        and geometry.period_steps >= 1
        and (geometry.period_steps >= 2 or geometry.year_span >= 2)
    )
    transposed_form = bool(geometry.transposed_period_axis) and (
        score.total >= TRANSPOSED_FLOOR
    )
    if not (main_form or fragment_form or block_form or transposed_form):
        return result
    group = ClaimGroup(
        family=FAMILY,
        score=score.total,
        state="reach",
        role=seat_role(geometry),
        channels=dict(score.by_channel),
        veto_flags=(),
        explained_foreign=0.0,
    )
    return CompetitionResult(
        claims=(FAMILY,),
        contested=result.contested,
        scores=result.scores,
        foreign_explained=result.foreign_explained,
        groups=result.groups + (group,),
    )


apply_lease_span_seat = seat_applier(_seat_one, "apply_lease_span_seat")
