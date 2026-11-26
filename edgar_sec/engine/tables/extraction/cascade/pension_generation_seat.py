"""Pension generation seat: the priced generation
admission for pension tables the scored floor never
surfaces. Final compete_filing pass: an unclaimed
geometry seats on note identity or quiet-form stubs.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    ClaimGroup,
    CompetitionResult,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.seats.seat_application import seat_role

FAMILY = "pension"

# Priced over the directed frame's enumerated missed
# population (348) against its unsurfaced not-pension
# population (963): the intersection converts 121 at 42.
NPBC_GROUPS = (
    ("service cost",),
    ("interest cost",),
    ("expected return",),
    (
        "amortization",
        "prior service",
        "actuarial",
        "net periodic",
        "settlement",
        "curtailment",
    ),
)
ASSUMPTION_COMPANIONS = ("expected", "compensation", "health")


def _quiet_form(geometry: GeometryText) -> bool:
    """The geometry's own stubs carry a pension form the
    scored floor prices too quietly to surface."""
    text = geometry.stub_text
    npbc = sum(1 for group in NPBC_GROUPS if any(term in text for term in group))
    pbo = "benefit obligation" in text
    fvpa = "fair value of plan assets" in text or "plan assets" in text
    if "funded status" in text and (pbo or fvpa):
        return True
    if npbc >= 2:
        return True
    if "discount rate" in text and any(term in text for term in ASSUMPTION_COMPANIONS):
        return True
    if "accumulated other comprehensive" in text and (
        "pension" in text or "postretirement" in text
    ):
        return True
    if "plan assets" in text and (
        "equity" in text or "fixed income" in text or "level" in text
    ):
        return True
    if "qualified pension plan" in text or "net amount recognized" in text:
        return True
    if "expected benefit payments" in text or (
        "expected employer contributions" in text
    ):
        return True
    return False


def _seat_one(
    geometry: GeometryText,
    result: CompetitionResult,
    anchor_notes: frozenset[int],
) -> CompetitionResult:
    """Seat pension on one unclaimed geometry, or don't."""
    if result.claims:
        return result
    note_leg = geometry.note_number is not None and geometry.note_number in anchor_notes
    if not (note_leg and _quiet_form(geometry)):
        return result
    score = result.scores.get(FAMILY)
    group = ClaimGroup(
        family=FAMILY,
        score=score.total if score is not None else 0.0,
        state="reach",
        role=seat_role(geometry),
        channels=dict(score.by_channel) if score is not None else {},
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


def apply_pension_generation_seat(
    geometries: list[GeometryText] | tuple[GeometryText, ...],
    results: list[CompetitionResult],
) -> list[CompetitionResult]:
    """Seat pension over the filing's gate-final unclaimed
    set under the generation admission."""
    anchor_notes = frozenset(
        geometry.note_number
        for geometry, result in zip(geometries, results, strict=True)
        if FAMILY in result.claims and geometry.note_number is not None
    )
    if not anchor_notes and not any(
        _quiet_form(geometry)
        for geometry, result in zip(geometries, results, strict=True)
        if not result.claims
    ):
        return results
    return [
        _seat_one(geometry, result, anchor_notes)
        for geometry, result in zip(geometries, results, strict=True)
    ]
