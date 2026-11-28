"""EPS formation seat: the priced tail seat for the
eps_reconciliation tables the chain left unclaimed.
Leg A seats on dominance with every admission form test
passed; leg B on a lead naming the calculation, guarded.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.core.term_index import TermEntry, TermIndex
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    ClaimGroup,
    CompetitionResult,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.core.text.normalize import normalize_text
from edgar_sec.engine.tables.extraction.seats.specs.eps_seat_specs import (
    CANDIDATE_ANATOMY_TERMS,
    CANDIDATE_GRID_TERMS,
    CANDIDATE_LEAD_TERMS,
    FAMILY,
    GUARD_RESTATEMENT_FLOOR,
    GUARD_RESTATEMENT_TERM,
    GUARD_WALK_FLOOR,
    LEG_A_FLOOR,
    LEG_A_FORM_TESTS,
    LEG_B_FLOOR,
    LEG_B_FORM_TESTS,
    LEG_B_LEAD_PHRASES,
    WALK_TEST,
)
from edgar_sec.engine.tables.extraction.seats.seat_application import (
    seat_applier,
    seat_role,
)
from edgar_sec.engine.tables.extraction.vetoes.precision_veto_evidence import (
    eps_context_only_fires,
    eps_restatement_face_fires,
)


def _form_passed(geometry: GeometryText, test_id: str) -> bool | None:
    """The eps outcome for one form test, or None if absent."""
    for outcome in geometry.form_tests:
        if outcome.family == FAMILY and outcome.test_id == test_id:
            return bool(outcome.passed)
    return None


_SEAT_INDEX = TermIndex(
    [TermEntry(term, "grid", value=term) for term in CANDIDATE_GRID_TERMS]
    + [TermEntry(term, "anatomy") for term in CANDIDATE_ANATOMY_TERMS]
    + [TermEntry(term, "lead") for term in CANDIDATE_LEAD_TERMS]
    + [TermEntry(phrase, "lead_b", value=phrase) for phrase in LEG_B_LEAD_PHRASES]
)


def _is_candidate(geometry: GeometryText) -> bool:
    """The priced candidate shape: both share bases in the
    grid, plus anatomy in stub/grid or a per-share lead."""
    grid = (geometry.grid_text or "").lower()
    stub = (geometry.stub_text or "").lower()
    lead = (geometry.lead or "").lower()
    grid_hits = _SEAT_INDEX.scan(grid)
    both = set(CANDIDATE_GRID_TERMS) <= set(grid_hits.get("grid", frozenset()))
    anatomy = "anatomy" in grid_hits or "anatomy" in _SEAT_INDEX.scan(stub)
    lead_in = "lead" in _SEAT_INDEX.scan(lead)
    return both and (anatomy or lead_in)


def _eps_total(result: CompetitionResult) -> float:
    """The geometry's eps score total, or zero if unscored."""
    score = result.scores.get(FAMILY)
    return score.total if score else 0.0


def _eps_top(result: CompetitionResult) -> bool:
    """Eps ties or beats every other family's score total."""
    totals = {family: score.total for family, score in result.scores.items()}
    return totals.get(FAMILY, 0.0) >= max(totals.values(), default=0.0)


def _guarded(geometry: GeometryText, result: CompetitionResult) -> bool:
    """A priced precision-refusal form matches this geometry:
    a registered eps leg, the restatement-note low-score
    form, or the walk-failed low-score form."""
    if eps_restatement_face_fires(geometry) or eps_context_only_fires(result):
        return True
    total = _eps_total(result)
    if (
        GUARD_RESTATEMENT_TERM in normalize_text(geometry.note_title or "")
        and total < GUARD_RESTATEMENT_FLOOR
    ):
        return True
    return total < GUARD_WALK_FLOOR and _form_passed(geometry, WALK_TEST) is False


def _leg_a(geometry: GeometryText, result: CompetitionResult) -> bool:
    """Dominance: eps top over the floor, all form tests passed."""
    return (
        _eps_top(result)
        and _eps_total(result) >= LEG_A_FLOOR
        and all(_form_passed(geometry, test_id) is True for test_id in LEG_A_FORM_TESTS)
    )


def _leg_b(geometry: GeometryText, result: CompetitionResult) -> bool:
    """Lead-named: eps over the floor, the lead names the
    calculation, evidence and detector passed."""
    lead = normalize_text(geometry.lead or "")
    return (
        _eps_total(result) >= LEG_B_FLOOR
        and set(LEG_B_LEAD_PHRASES)
        <= set(_SEAT_INDEX.scan(lead).get("lead_b", frozenset()))
        and all(_form_passed(geometry, test_id) is True for test_id in LEG_B_FORM_TESTS)
    )


def _seat_one(geometry: GeometryText, result: CompetitionResult) -> CompetitionResult:
    """Seat eps_reconciliation on one unclaimed geometry, or don't."""
    if result.claims or not _is_candidate(geometry):
        return result
    if _guarded(geometry, result):
        return result
    if not (_leg_a(geometry, result) or _leg_b(geometry, result)):
        return result
    score = result.scores[FAMILY]
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


apply_eps_seat = seat_applier(_seat_one, "apply_eps_seat")
