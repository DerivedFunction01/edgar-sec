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


def _seat_one(geometry: GeometryText, result: CompetitionResult) -> CompetitionResult:
    """Seat lease_maturity on one unclaimed geometry, or don't."""
    if result.claims:
        return result
    if any(group.family == FAMILY for group in result.groups):
        return result
    score = result.scores.get(FAMILY)
    if score is None or score.total < SEAT_FLOOR:
        return result
    if geometry.year_span < SPAN_MIN:
        return result
    if geometry.stub_ladder_purity < PURITY_MIN:
        return result
    if debt_seat_claimed(geometry.form_tests):
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
