"""Pension generation seat: the priced generation
admission for pension tables the scored floor never
surfaces. Final compete_filing pass: an unclaimed
geometry seats on note identity and composed-form stubs.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    ClaimGroup,
    CompetitionResult,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.core.text.normalize import normalize_text
from edgar_sec.engine.tables.extraction.pension.pension_evidence import (
    PENSION_ANCHOR_SPECS,
    PensionText,
    pension_anchor_set,
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


# The composed definition's extension clauses, from the
# fragment-form vocabulary census: each priced singly
# and in combination at zero falses (board 751/700).
def _rollforward_form(geometry: GeometryText) -> bool:
    """AOCI rollforward row-shape: a balance row, an
    arising-during row, a net amortization row."""
    text = geometry.stub_text
    return "balance" in text and "arising during" in text and "amortization" in text


def _conjoined_form(geometry: GeometryText) -> bool:
    """One stub carrying both NPBC components conjoined:
    'service and interest cost'."""
    return any("service and interest cost" in stub for stub in geometry.stubs)


def _crediting_form(geometry: GeometryText) -> bool:
    """Assumptions companion: discount rate stated with
    a crediting rate."""
    text = geometry.stub_text
    return "discount rate" in text and "crediting rate" in text


def _return_form(geometry: GeometryText) -> bool:
    """Assumptions companion: discount rate stated with
    a rate of return."""
    text = geometry.stub_text
    return "discount rate" in text and "rate of return" in text


def _asset_return_form(geometry: GeometryText) -> bool:
    """Assets-leg companion: plan assets with an actual
    return or gain."""
    text = geometry.stub_text
    return "plan assets" in text and ("actual return" in text or "actual gain" in text)


def _capitalized_form(geometry: GeometryText) -> bool:
    """Genuine-only phrase of the census read:
    'capitalized portion'."""
    return "capitalized portion" in geometry.stub_text


def _definition_form(geometry: GeometryText) -> bool:
    """The composed definition: the production quiet
    form or any priced extension clause."""
    return (
        _quiet_form(geometry)
        or _rollforward_form(geometry)
        or _conjoined_form(geometry)
        or _crediting_form(geometry)
        or _return_form(geometry)
        or _asset_return_form(geometry)
        or _capitalized_form(geometry)
    )


_SEP_HINTS = (
    "cell fired",
    "summary separator",
    "seg:",
    "rows_le_2",
    "inc:",
    "host_stubkey",
    "revenue_stub",
)


def _funded_only_form(geometry: GeometryText, result: CompetitionResult) -> bool:
    """C-SEAT-NARROW admission (the priced stage
    divergence cure): sole anchor leg the funded leg
    on the bare term, no veto or separator kill."""
    spec = PENSION_ANCHOR_SPECS.get(FAMILY)
    if spec is None:
        return False
    text = PensionText.from_geometry(geometry)
    if pension_anchor_set(text, spec) != frozenset({"funded"}):
        return False
    stubtext = (
        "\n".join(normalize_text(stub) for stub in text.stubs)
        + "\n"
        + normalize_text(text.prose_after)
    )
    if "benefit obligation" not in stubtext:
        return False
    if any(
        term in stubtext for term in spec.funded_terms if term != "benefit obligation"
    ):
        return False
    score = result.scores.get(FAMILY)
    if score is None:
        return True
    return not any(
        entry.channel == "veto"
        or (
            entry.channel == "gate" and any(hint in entry.detail for hint in _SEP_HINTS)
        )
        for entry in score.evidence
    )


def _seat_one(
    geometry: GeometryText,
    result: CompetitionResult,
    anchor_notes: frozenset[int],
) -> CompetitionResult:
    """Seat pension on one unclaimed geometry, or don't."""
    if result.claims:
        return result
    note_leg = geometry.note_number is not None and geometry.note_number in anchor_notes
    if not note_leg:
        return result
    if not (_definition_form(geometry) or _funded_only_form(geometry, result)):
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
        _definition_form(geometry)
        for geometry, result in zip(geometries, results, strict=True)
        if not result.claims
    ):
        return results
    return [
        _seat_one(geometry, result, anchor_notes)
        for geometry, result in zip(geometries, results, strict=True)
    ]
