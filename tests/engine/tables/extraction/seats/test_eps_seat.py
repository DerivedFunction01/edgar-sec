"""EPS formation seat: the guarded tail seat over the
gate-final unclaimed geometries the chain left unclaimed.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.cascade.filing_competition import (
    compete_filing,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    CompetitionResult,
    FamilyScore,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_types import (
    FormTestOutcome,
)
from edgar_sec.engine.tables.extraction.seats.eps_seat import apply_eps_seat

EPS = "eps_reconciliation"

_GRID = (
    "net income weighted average shares basic diluted "
    "dilutive securities earnings per share"
)
_LEAD_B = (
    "The following table summarizes the calculation of "
    "basic and diluted earnings per share"
)


def _outcome(test_id: str, passed: bool) -> FormTestOutcome:
    return FormTestOutcome(
        family=EPS,
        test_id=test_id,
        kind="core",
        passed=passed,
        evaluable=True,
        columns_closed=0,
        points=3.0,
        detail="",
    )


def _leg_a_tests() -> tuple[FormTestOutcome, ...]:
    return (
        _outcome("eps_evidence", True),
        _outcome("eps_detector", True),
        _outcome("eps_proforma_refusal", True),
        _outcome("eps_reconciliation_form_separation", True),
    )


def _result(
    eps_total: float | None,
    claims: tuple[str, ...] = (),
    other: float | None = None,
    channels: dict[str, float] | None = None,
) -> CompetitionResult:
    scores: dict[str, FamilyScore] = {}
    if eps_total is not None:
        scores[EPS] = FamilyScore(EPS, eps_total, channels or {"stub": eps_total}, ())
    if other is not None:
        scores["deferred_tax"] = FamilyScore("deferred_tax", other, {"stub": other}, ())
    return CompetitionResult(claims=claims, contested=(), scores=scores)


def _geometry(**kw: object) -> GeometryText:
    base: dict = {"grid_text": _GRID, "form_tests": _leg_a_tests()}
    base.update(kw)
    return GeometryText(**base)  # type: ignore[arg-type]


def _seat(geometry: GeometryText, result: CompetitionResult) -> CompetitionResult:
    (out,) = apply_eps_seat([geometry], [result])
    return out


def test_leg_a_seats_a_dominant_unclaimed_geometry() -> None:
    result = _result(20.0, other=10.0)
    out = _seat(_geometry(), result)
    assert out.claims == (EPS,)
    (group,) = out.groups
    assert group.family == EPS
    assert group.state == "reach"
    assert group.score == 20.0
    assert out.scores is result.scores


def test_leg_a_seats_at_the_floor() -> None:
    out = _seat(_geometry(), _result(15.0, other=15.0))
    assert out.claims == (EPS,)


def test_leg_b_seats_a_lead_named_geometry_without_dominance() -> None:
    geometry = _geometry(
        lead=_LEAD_B,
        form_tests=(
            _outcome("eps_evidence", True),
            _outcome("eps_detector", True),
        ),
    )
    out = _seat(geometry, _result(44.0, other=50.0))
    assert out.claims == (EPS,)


def test_seat_refuses_a_claimed_geometry() -> None:
    result = _result(20.0, claims=("income_statement",), other=10.0)
    out = _seat(_geometry(), result)
    assert out is result


def test_seat_refuses_a_non_candidate_geometry() -> None:
    geometry = _geometry(grid_text="net income weighted average shares basic")
    out = _seat(geometry, _result(20.0, other=10.0))
    assert out.claims == ()


def test_seat_refuses_below_the_leg_a_floor() -> None:
    out = _seat(_geometry(), _result(14.9, other=1.0))
    assert out.claims == ()


def test_seat_refuses_without_an_eps_score() -> None:
    out = _seat(_geometry(), _result(None, other=1.0))
    assert out.claims == ()


def test_seat_refuses_when_a_leg_a_form_test_failed() -> None:
    geometry = _geometry(
        form_tests=(
            _outcome("eps_evidence", True),
            _outcome("eps_detector", False),
            _outcome("eps_proforma_refusal", True),
            _outcome("eps_reconciliation_form_separation", True),
        )
    )
    out = _seat(geometry, _result(20.0, other=10.0))
    assert out.claims == ()


def test_seat_refuses_when_a_leg_a_form_test_is_absent() -> None:
    geometry = _geometry(
        form_tests=(
            _outcome("eps_evidence", True),
            _outcome("eps_detector", True),
            _outcome("eps_reconciliation_form_separation", True),
        )
    )
    out = _seat(geometry, _result(20.0, other=10.0))
    assert out.claims == ()


def test_seat_refuses_a_dominated_geometry_without_a_leg_b_lead() -> None:
    out = _seat(_geometry(), _result(20.0, other=30.0))
    assert out.claims == ()


def test_guard_refuses_the_restatement_face_statement_form() -> None:
    geometry = _geometry(
        headers=("As Previously Reported", "Adjustments", "As Restated"),
        stubs=("Consolidated statements of operations",),
    )
    out = _seat(geometry, _result(20.0, other=10.0))
    assert out.claims == ()


def test_guard_refuses_the_context_only_form() -> None:
    geometry = _geometry(
        lead=_LEAD_B,
        form_tests=(
            _outcome("eps_evidence", True),
            _outcome("eps_detector", True),
        ),
    )
    result = _result(44.0, other=10.0, channels={"context": 44.0})
    out = _seat(geometry, result)
    assert out.claims == ()


def test_guard_refuses_the_restatement_note_low_score_form() -> None:
    geometry = _geometry(note_title="Restatement of consolidated financial statements")
    out = _seat(geometry, _result(18.0, other=10.0))
    assert out.claims == ()


def test_compete_filing_leaves_a_scoreless_geometry_unclaimed() -> None:
    (out,) = compete_filing([GeometryText()])
    assert out.claims == ()
