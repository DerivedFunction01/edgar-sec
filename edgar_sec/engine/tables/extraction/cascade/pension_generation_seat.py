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
from edgar_sec.engine.tables.extraction.core.term_index import TermEntry, TermIndex
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

_QUIET_TERMS = (
    "benefit obligation",
    "fair value of plan assets",
    "plan assets",
    "funded status",
    "discount rate",
    "accumulated other comprehensive",
    "pension",
    "postretirement",
    "equity",
    "fixed income",
    "level",
    "qualified pension plan",
    "net amount recognized",
    "expected benefit payments",
    "expected employer contributions",
    "balance",
    "arising during",
    "amortization",
    "crediting rate",
    "rate of return",
    "actual return",
    "actual gain",
    "capitalized portion",
)


def _seat_index() -> TermIndex:
    """One substring index over the seat's stub terms: kind is
    the term itself; npbc groups and companions ride own kinds.
    Phrase entries only — the seat's matching is literal
    substring for single words too."""
    entries = [TermEntry(term, term) for term in _QUIET_TERMS]
    for i, group in enumerate(NPBC_GROUPS):
        entries.extend(TermEntry(term, f"npbc:{i}") for term in group)
    entries.extend(TermEntry(term, "companion") for term in ASSUMPTION_COMPANIONS)
    return TermIndex(entries)


_SEAT_INDEX = _seat_index()


def _stub_hits(text: str) -> frozenset[str]:
    """The seat terms present in one stub text, one traversal."""
    found = _SEAT_INDEX.scan(text)
    return frozenset(
        value
        for kind, values in found.items()
        if not kind.startswith("npbc:")
        for value in values
    )


def _quiet_form(geometry: GeometryText) -> bool:
    """The geometry's own stubs carry a pension form the
    scored floor prices too quietly to surface."""
    text = geometry.stub_text
    found = _SEAT_INDEX.scan(text)
    hits = _stub_hits(text)
    npbc = sum(1 for i in range(len(NPBC_GROUPS)) if f"npbc:{i}" in found)
    pbo = "benefit obligation" in hits
    fvpa = "fair value of plan assets" in hits or "plan assets" in hits
    if "funded status" in hits and (pbo or fvpa):
        return True
    if npbc >= 2:
        return True
    if "discount rate" in hits and "companion" in found:
        return True
    if "accumulated other comprehensive" in hits and (
        "pension" in hits or "postretirement" in hits
    ):
        return True
    if "plan assets" in hits and (
        "equity" in hits or "fixed income" in hits or "level" in hits
    ):
        return True
    if "qualified pension plan" in hits or "net amount recognized" in hits:
        return True
    if "expected benefit payments" in hits or (
        "expected employer contributions" in hits
    ):
        return True
    return False


# The composed definition's extension clauses, from the
# fragment-form vocabulary census: each priced singly
# and in combination at zero falses (board 751/700).
def _rollforward_form(geometry: GeometryText) -> bool:
    """AOCI rollforward row-shape: a balance row, an
    arising-during row, a net amortization row."""
    hits = _stub_hits(geometry.stub_text)
    return "balance" in hits and "arising during" in hits and "amortization" in hits


def _conjoined_form(geometry: GeometryText) -> bool:
    """One stub carrying both NPBC components conjoined:
    'service and interest cost'."""
    return any("conjoined" in _CONJOINED_INDEX.scan(stub) for stub in geometry.stubs)


def _crediting_form(geometry: GeometryText) -> bool:
    """Assumptions companion: discount rate stated with
    a crediting rate."""
    hits = _stub_hits(geometry.stub_text)
    return "discount rate" in hits and "crediting rate" in hits


def _return_form(geometry: GeometryText) -> bool:
    """Assumptions companion: discount rate stated with
    a rate of return."""
    hits = _stub_hits(geometry.stub_text)
    return "discount rate" in hits and "rate of return" in hits


def _asset_return_form(geometry: GeometryText) -> bool:
    """Assets-leg companion: plan assets with an actual
    return or gain."""
    hits = _stub_hits(geometry.stub_text)
    return "plan assets" in hits and ("actual return" in hits or "actual gain" in hits)


def _capitalized_form(geometry: GeometryText) -> bool:
    """Genuine-only phrase of the census read:
    'capitalized portion'."""
    return "capitalized portion" in _stub_hits(geometry.stub_text)


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

_CONJOINED_INDEX = TermIndex(
    (TermEntry("service and interest cost", "conjoined"),)
)
_HINT_INDEX = TermIndex(TermEntry(hint, hint) for hint in _SEP_HINTS)
_FUNDED_INDEX = TermIndex(
    TermEntry(term, term)
    for term in PENSION_ANCHOR_SPECS[FAMILY].funded_terms
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
    funded_hits = _FUNDED_INDEX.scan(stubtext)
    if "benefit obligation" not in funded_hits:
        return False
    if any(term in funded_hits for term in spec.funded_terms if term != "benefit obligation"):
        return False
    score = result.scores.get(FAMILY)
    if score is None:
        return True
    # A veto entry on the funded anchor term itself is
    # not a kill: the funded evidence, read by another channel.
    return not any(
        (entry.channel == "veto" and entry.detail != "term:benefit obligation")
        or (entry.channel == "gate" and bool(_HINT_INDEX.scan(entry.detail)))
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
