"""Warrant seat: the formation seat on the gate-final set the
family's two form tests cannot claim alone (legs priced on the
enlarged adjudicated set, register-warrant-activity.md).
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
from edgar_sec.engine.tables.extraction.seats.warrant_seat import apply_warrant_seat

W = "warrant_activity"
ROLL = "warrant_activity_rollforward"
LIST = "warrant_outstanding_listing"
INTRO = "the following table summarizes warrant activity"


def _outcome(test_id: str, passed: bool, groups: tuple[bool, ...]) -> FormTestOutcome:
    return FormTestOutcome(
        family=W,
        test_id=test_id,
        kind="measure_set",
        passed=passed,
        evaluable=True,
        columns_closed=0,
        points=3.0,
        detail="",
        groups=groups,
    )


def _result(
    claims: tuple[str, ...] = (), score: float | None = None
) -> CompetitionResult:
    scores = {}
    if score is not None:
        scores[W] = FamilyScore(W, score, {"form_test": score}, ())
    return CompetitionResult(claims=claims, contested=(), scores=scores)


def _seat(geometries: list[GeometryText], results: list[CompetitionResult]):
    return apply_warrant_seat(geometries, results)


def test_leg_a_seats_an_unclaimed_test_pass() -> None:
    geometry = GeometryText(
        stubs=("warrants outstanding at beginning of period",),
        form_tests=(_outcome(ROLL, True, (True,) * 6),),
    )
    (out,) = _seat([geometry], [_result(score=3.0)])
    assert out.claims == (W,)
    (group,) = out.groups
    assert group.family == W
    assert group.state == "reach"
    assert group.score == 3.0


def test_leg_a_refuses_a_cover_claimed_geometry() -> None:
    geometry = GeometryText(form_tests=(_outcome(ROLL, True, (True,) * 6),))
    result = _result(claims=("cover_layout",))
    (out,) = _seat([geometry], [result])
    assert out is result


def test_already_claimed_warrant_is_untouched() -> None:
    geometry = GeometryText(form_tests=(_outcome(ROLL, True, (True,) * 6),))
    result = _result(claims=(W,))
    (out,) = _seat([geometry], [result])
    assert out is result


def test_leg_b_seats_on_the_extinguishment_extension() -> None:
    geometry = GeometryText(
        stubs=("warrants extinguished",),
        form_tests=(_outcome(ROLL, False, (True, True, False, False, True, False)),),
    )
    (out,) = _seat([geometry], [_result(claims=("fair_value",))])
    assert out.claims == ("fair_value", W)


def test_leg_b_refuses_without_the_extension() -> None:
    geometry = GeometryText(
        stubs=("warrants granted",),
        form_tests=(_outcome(ROLL, False, (True, True, False, False, True, False)),),
    )
    result = _result(claims=("fair_value",))
    (out,) = _seat([geometry], [result])
    assert out is result


def test_leg_b_seats_on_dated_bookend_folding() -> None:
    geometry = GeometryText(
        stubs=("warrants outstanding", "december 31, 2023", "december 31, 2024"),
        form_tests=(_outcome(ROLL, False, (False, True, True, True, False, False)),),
    )
    (out,) = _seat([geometry], [_result(claims=("fair_value",))])
    assert out.claims == ("fair_value", W)


def test_leg_c_seats_on_the_introducing_clause() -> None:
    geometry = GeometryText(
        prose_tail=INTRO,
        form_tests=(_outcome(LIST, False, (True, False, True, False)),),
    )
    (out,) = _seat([geometry], [_result()])
    assert out.claims == (W,)


def test_leg_c_refuses_an_option_naming_clause() -> None:
    geometry = GeometryText(
        prose_tail="the following table summarizes option and warrant activity",
        form_tests=(_outcome(LIST, False, (True, False, True, False)),),
    )
    (out,) = _seat([geometry], [_result()])
    assert out.claims == ()


def test_leg_d_seats_a_fair_value_walk_on_intro() -> None:
    geometry = GeometryText(
        prose_tail=INTRO,
        form_tests=(_outcome(ROLL, False, (False,) * 6),),
    )
    (out,) = _seat([geometry], [_result(claims=("fair_value",))])
    assert out.claims == ("fair_value", W)


def test_leg_d_refuses_a_mixed_claim_set() -> None:
    geometry = GeometryText(
        prose_tail=INTRO,
        form_tests=(_outcome(ROLL, False, (False,) * 6),),
    )
    result = _result(claims=("fair_value", "eps_reconciliation"))
    (out,) = _seat([geometry], [result])
    assert out is result


def test_leg_g2_co_seats_a_test_pass_claimed_elsewhere() -> None:
    geometry = GeometryText(form_tests=(_outcome(LIST, True, (True,) * 4),))
    (out,) = _seat([geometry], [_result(claims=("inventory",))])
    assert out.claims == ("inventory", W)


def test_leg_e_seats_a_one_short_rollforward_with_intro() -> None:
    geometry = GeometryText(
        stubs=("warrants outstanding at beginning of period",),
        prose_tail=INTRO,
        form_tests=(_outcome(ROLL, False, (True, True, True, False, False, False)),),
    )
    (out,) = _seat([geometry], [_result()])
    assert out.claims == (W,)


def test_leg_e_refuses_without_corroboration() -> None:
    geometry = GeometryText(
        stubs=("warrants outstanding at beginning of period",),
        form_tests=(_outcome(ROLL, False, (True, True, True, False, False, False)),),
    )
    (out,) = _seat([geometry], [_result()])
    assert out.claims == ()


def test_leg_c3_seats_a_weak_rollforward_with_subject_and_intro() -> None:
    geometry = GeometryText(
        stubs=("warrants granted",),
        prose_tail=INTRO,
        form_tests=(_outcome(ROLL, False, (False, True, False, False, True, False)),),
    )
    (out,) = _seat([geometry], [_result()])
    assert out.claims == (W,)


def test_leg_f_seats_beside_a_seated_sibling() -> None:
    head = GeometryText(form_tests=(_outcome(ROLL, True, (True,) * 6),))
    pair = GeometryText(
        stubs=("warrants granted",),
        prose_tail=INTRO,
        form_tests=(
            _outcome(ROLL, False, (False, True, False, False, False, False)),
            _outcome(LIST, False, (True, False, False, False)),
        ),
    )
    out = _seat([head, pair], [_result(), _result()])
    assert out[0].claims == (W,)
    assert out[1].claims == (W,)


def test_leg_f_refuses_below_the_candidate_floor() -> None:
    head = GeometryText(form_tests=(_outcome(ROLL, True, (True,) * 6),))
    pair = GeometryText(
        stubs=("warrants granted",),
        form_tests=(_outcome(ROLL, False, (False, True, False, False, True, False)),),
    )
    out = _seat([head, pair], [_result(), _result()])
    assert out[0].claims == (W,)
    assert out[1].claims == ()


def test_leg_g2_refuses_a_valuation_assumptions_claim() -> None:
    geometry = GeometryText(form_tests=(_outcome(LIST, True, (True,) * 4),))
    result = _result(claims=("valuation_model_assumptions",))
    (out,) = _seat([geometry], [result])
    assert out is result


def test_leg_f_refuses_without_a_seated_sibling() -> None:
    pair = GeometryText(
        stubs=("warrants granted",),
        form_tests=(_outcome(ROLL, False, (False, True, False, False, True, False)),),
    )
    (out,) = _seat([pair], [_result()])
    assert out.claims == ()


def test_compete_filing_leaves_a_scoreless_geometry_unclaimed() -> None:
    (out,) = compete_filing([GeometryText()])
    assert out.claims == ()
