"""Segment seat: the priced formation seat for segment tables
whose own score stays under the claim floor.

Final compete_filing pass: an unclaimed geometry seats
segment_reporting when its two readers agree.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    ClaimGroup,
    CompetitionResult,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.cascade.residue_families import (
    segment_geographic_partition,
    segment_grid,
    segment_header_partition,
)
from edgar_sec.engine.tables.extraction.seats.seat_application import (
    seat_applier,
    seat_role,
)
from edgar_sec.engine.tables.extraction.vetoes.term_vetoes import term_veto_hits

FAMILY = "segment_reporting"
CORE_FORM_TEST = "segment_reporting_core_form"

# Priced by the segment-formation trade curve over the frame:
# the balanced cell (7 conversions, 0 classified false adds).
SEAT_FLOOR = 3.5
SEAT_RATIO = 0.75


def _core_form_passed(geometry: GeometryText) -> bool:
    """The family's core form test passed on this geometry."""
    for outcome in geometry.form_tests:
        if outcome.family == FAMILY and outcome.test_id == CORE_FORM_TEST:
            return outcome.passed
    return False


def _seat_one(geometry: GeometryText, result: CompetitionResult) -> CompetitionResult:
    """Seat segment_reporting on one unclaimed geometry, or don't."""
    if result.claims:
        return result
    separator = geometry.summary_separator
    if separator is not None and separator.fired:
        return result
    if "hard" in (term_veto_hits(geometry).get(FAMILY) or {}):
        return result
    score = result.scores.get(FAMILY)
    if score is None or score.total < SEAT_FLOOR:
        return result
    best_other = max(
        (s.total for family, s in result.scores.items() if family != FAMILY),
        default=0.0,
    )
    if score.total < SEAT_RATIO * best_other:
        return result
    if not _core_form_passed(geometry):
        return result
    if not (
        segment_grid(geometry)
        or segment_header_partition(geometry)
        or segment_geographic_partition(geometry)
    ):
        return result
    role = seat_role(geometry)
    group = ClaimGroup(
        family=FAMILY,
        score=score.total,
        state="reach",
        role=role,
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


apply_segment_seat = seat_applier(_seat_one, "apply_segment_seat")
