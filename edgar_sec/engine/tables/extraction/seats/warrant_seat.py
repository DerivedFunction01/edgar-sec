"""Warrant seat: the priced formation seat for warrant tables
the chain leaves unclaimed or fair_value-claimed.

Final compete_filing pass; legs priced on the enlarged
adjudicated set (register-warrant-activity.md): P .938 / R .938.
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
from edgar_sec.engine.tables.extraction.form_specs.form_test_types import (
    FormTestOutcome,
)
from edgar_sec.engine.tables.extraction.form_tests.measure_set import (
    _DATED_BOOKEND_RE,
    _present,
)
from edgar_sec.engine.tables.extraction.seats.seat_application import seat_role

FAMILY = "warrant_activity"
ROLL = "warrant_activity_rollforward"
LIST = "warrant_outstanding_listing"
INTRO_MARKERS = ("following", "as follows", "summar", "lists", "schedule of")
EXTINGUISHMENT_TERMS = ("extinguishment", "extinguished", "surrender")
ROLL_MIN = 4
LIST_MIN = 2


def _outcome(geometry: GeometryText, test_id: str) -> FormTestOutcome | None:
    """The family's named form-test outcome, if it was evaluated."""
    for outcome in geometry.form_tests:
        if outcome.family == FAMILY and outcome.test_id == test_id:
            return outcome
    return None


def _test_passed(geometry: GeometryText) -> bool:
    """Either production warrant test passed on this geometry."""
    return any(
        outcome is not None and outcome.passed
        for outcome in (_outcome(geometry, ROLL), _outcome(geometry, LIST))
    )


def _group_count(geometry: GeometryText, test_id: str) -> int:
    """The spec's raw group-presence count from its outcome."""
    outcome = _outcome(geometry, test_id)
    if outcome is None:
        return 0
    return sum(outcome.groups)


def _texts(geometry: GeometryText) -> list[str]:
    """The seat's match universe: stubs, caption, header cells."""
    texts = [normalize_text(stub) for stub in geometry.stubs]
    texts.append(normalize_text(geometry.caption))
    texts.extend(normalize_text(cell) for cell in geometry.headers)
    return [text for text in texts if text]


def _subject_on_table(geometry: GeometryText) -> bool:
    """The warrant subject is present in the table's own texts."""
    return _present(_texts(geometry), ("warrant",))


def _prose_introduces(geometry: GeometryText) -> bool:
    """The prose tail's final clause introduces a warrant table:
    it names a warrant, names no option, and carries a marker."""
    tail = geometry.prose_tail
    if "warrant" not in tail:
        return False
    cut = max(tail.rfind(". "), tail.rfind(": "), tail.rfind("\n"))
    clause = tail[cut + 1 :].strip() if cut >= 0 else tail
    if "warrant" not in clause or "option" in clause:
        return False
    return any(marker in clause for marker in INTRO_MARKERS)


def _liability_pass(geometry: GeometryText) -> bool:
    """The liability variant of the rollforward spec, evaluated
    seat-side: base groups, extinguishment/surrender in the
    exercised-class group, dated bookends folded in."""
    outcome = _outcome(geometry, ROLL)
    if outcome is None or len(outcome.groups) != 6:
        return False
    texts = _texts(geometry)
    if not _present(texts, ("warrant",)):
        return False
    present = list(outcome.groups)
    present[3] = present[3] or _present(texts, EXTINGUISHMENT_TERMS)
    dated = {text for text in texts if _DATED_BOOKEND_RE.match(text)}
    if dated:
        present[0] = True
        if len(dated) >= 2:
            present[4] = True
    return sum(present) >= ROLL_MIN


def _seat(geometry: GeometryText, result: CompetitionResult) -> CompetitionResult:
    """Append the warrant claim and its reach group."""
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
        claims=result.claims + (FAMILY,),
        contested=result.contested,
        scores=result.scores,
        foreign_explained=result.foreign_explained,
        groups=result.groups + (group,),
    )


def _apply_legs(geometry: GeometryText, result: CompetitionResult) -> CompetitionResult:
    """Legs A-G2-E-C3 on one geometry, in priced order."""
    if FAMILY in result.claims:
        return result
    claims = result.claims
    passed = _test_passed(geometry)
    if not claims and passed:
        return _seat(geometry, result)
    if claims == ("fair_value",) and _liability_pass(geometry):
        return _seat(geometry, result)
    if (
        not claims
        and not passed
        and _prose_introduces(geometry)
        and _group_count(geometry, LIST) >= LIST_MIN
    ):
        return _seat(geometry, result)
    if claims == ("fair_value",) and _prose_introduces(geometry):
        return _seat(geometry, result)
    if claims and "cover_layout" not in claims and passed:
        return _seat(geometry, result)
    if (
        not claims
        and _group_count(geometry, ROLL) >= 3
        and _subject_on_table(geometry)
        and (_prose_introduces(geometry) or _liability_pass(geometry))
    ):
        return _seat(geometry, result)
    if (
        not claims
        and not passed
        and _prose_introduces(geometry)
        and _subject_on_table(geometry)
        and _group_count(geometry, ROLL) >= 2
    ):
        return _seat(geometry, result)
    return result


def _pair_seat(
    geometry: GeometryText,
    result: CompetitionResult,
    base_claims: tuple[str, ...],
    seated: list[CompetitionResult],
    index: int,
) -> CompetitionResult:
    """Leg F: a subject- or intro-bearing skeleton geometry seats
    when a sibling geometry in the filing is warrant-seated."""
    if FAMILY in result.claims:
        return result
    if base_claims not in ((), ("fair_value",)):
        return result
    if not (_subject_on_table(geometry) or _prose_introduces(geometry)):
        return result
    if _group_count(geometry, ROLL) < 2 and _group_count(geometry, LIST) < 1:
        return result
    if not any(
        FAMILY in other.claims
        for position, other in enumerate(seated)
        if position != index
    ):
        return result
    return _seat(geometry, result)


def apply_warrant_seat(
    geometries: list[GeometryText] | tuple[GeometryText, ...],
    results: list[CompetitionResult],
) -> list[CompetitionResult]:
    """Seat warrant_activity across one filing: per-geometry legs
    first, the pair seat over their output last."""
    seated = [
        _apply_legs(geometry, result)
        for geometry, result in zip(geometries, results, strict=True)
    ]
    return [
        _pair_seat(geometry, result, base.claims, seated, index)
        for index, (geometry, result, base) in enumerate(
            zip(geometries, seated, results, strict=True)
        )
    ]
