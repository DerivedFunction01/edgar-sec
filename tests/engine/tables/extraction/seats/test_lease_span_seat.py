"""Lease span seat: the formation seat on gate-final
unclaimed lease ladders, guarded by the debt seat's claim.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    ClaimGroup,
    CompetitionResult,
    FamilyScore,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_types import (
    FormTestOutcome,
)
from edgar_sec.engine.tables.extraction.seats.lease_span_seat import (
    apply_lease_span_seat,
)

LEASE = "lease_maturity"
DEBT = "debt_maturity"


def _debt_outcome(test_id: str, passed: bool) -> FormTestOutcome:
    return FormTestOutcome(
        family=DEBT,
        test_id=test_id,
        kind="ladder",
        passed=passed,
        evaluable=True,
        columns_closed=0,
        points=0.0,
        detail="",
    )


_DEBT_SEATED = (
    _debt_outcome("debt_maturity_year_ladder", True),
    _debt_outcome("debt_maturity_j1_admission", True),
)
_DEBT_UNSEATED = (
    _debt_outcome("debt_maturity_year_ladder", True),
    _debt_outcome("debt_maturity_j1_admission", False),
)


def _geometry(**kw: object) -> GeometryText:
    base: dict = {"year_span": 5, "stub_ladder_purity": 1.0, "form_tests": ()}
    base.update(kw)
    return GeometryText(**base)  # type: ignore[arg-type]


def _result(
    lease_total: float | None,
    claims: tuple[str, ...] = (),
    groups: tuple[ClaimGroup, ...] = (),
) -> CompetitionResult:
    scores: dict[str, FamilyScore] = {}
    if lease_total is not None:
        scores[LEASE] = FamilyScore(LEASE, lease_total, {"signature": lease_total}, ())
    return CompetitionResult(claims=claims, contested=(), scores=scores, groups=groups)


def _seat(geometry: GeometryText, result: CompetitionResult) -> CompetitionResult:
    (out,) = apply_lease_span_seat([geometry], [result])
    return out


def test_seat_fires_on_a_clean_ladder() -> None:
    result = _result(16.0)
    out = _seat(_geometry(), result)
    assert out.claims == (LEASE,)
    (group,) = out.groups
    assert group.family == LEASE
    assert group.state == "reach"
    assert group.score == 16.0
    assert out.scores is result.scores


def test_seat_fires_at_the_priced_bounds() -> None:
    geometry = _geometry(year_span=4, stub_ladder_purity=0.7)
    out = _seat(geometry, _result(15.0))
    assert out.claims == (LEASE,)


def test_seat_refuses_a_claimed_geometry() -> None:
    result = _result(16.0, claims=("income_statement",))
    out = _seat(_geometry(), result)
    assert out is result


def test_seat_refuses_a_geometry_with_a_lease_group() -> None:
    group = ClaimGroup(LEASE, 0.0, "reach", "head", {}, (), 0.0)
    out = _seat(_geometry(), _result(16.0, groups=(group,)))
    assert out.claims == ()


def test_seat_refuses_below_the_score_floor() -> None:
    out = _seat(_geometry(), _result(14.9))
    assert out.claims == ()


def test_seat_refuses_without_a_lease_score() -> None:
    out = _seat(_geometry(), _result(None))
    assert out.claims == ()


def test_seat_refuses_below_the_span() -> None:
    out = _seat(_geometry(year_span=3), _result(16.0))
    assert out.claims == ()


def test_seat_refuses_below_the_purity() -> None:
    out = _seat(_geometry(stub_ladder_purity=0.69), _result(16.0))
    assert out.claims == ()


def test_seat_refuses_when_the_debt_seat_claims_the_geometry() -> None:
    out = _seat(_geometry(form_tests=_DEBT_SEATED), _result(16.0))
    assert out.claims == ()


def test_seat_fires_when_the_debt_seat_does_not_claim() -> None:
    out = _seat(_geometry(form_tests=_DEBT_UNSEATED), _result(16.0))
    assert out.claims == (LEASE,)


def test_seat_fires_on_period_steps_below_the_year_span() -> None:
    out = _seat(_geometry(year_span=2, period_steps=3), _result(16.0))
    assert out.claims == (LEASE,)


def test_seat_refuses_below_the_period_steps() -> None:
    out = _seat(_geometry(year_span=2, period_steps=1), _result(16.0))
    assert out.claims == ()


def test_seat_fires_on_period_purity_for_a_band_ladder() -> None:
    out = _seat(
        _geometry(
            year_span=0, period_steps=6, stub_ladder_purity=0.33, period_purity=0.89
        ),
        _result(16.0),
    )
    assert out.claims == (LEASE,)


def test_seat_refuses_when_both_purities_are_low() -> None:
    out = _seat(
        _geometry(
            year_span=0, period_steps=6, stub_ladder_purity=0.33, period_purity=0.5
        ),
        _result(16.0),
    )
    assert out.claims == ()


def test_seat_fires_on_block_purity_past_a_reconciliation_tail() -> None:
    out = _seat(
        _geometry(stub_ladder_purity=0.5, period_purity=0.5, block_purity=1.0),
        _result(16.0),
    )
    assert out.claims == (LEASE,)


def test_seat_fires_the_fragment_arm_on_a_short_pure_ladder() -> None:
    out = _seat(
        _geometry(year_span=2, period_steps=2, stub_ladder_purity=1.0),
        _result(11.0),
    )
    assert out.claims == (LEASE,)


def test_seat_refuses_the_fragment_arm_below_its_floor() -> None:
    out = _seat(
        _geometry(year_span=2, period_steps=2, stub_ladder_purity=1.0),
        _result(7.0),
    )
    assert out.claims == ()


def test_seat_fires_the_transposed_arm() -> None:
    out = _seat(
        _geometry(
            year_span=0,
            period_steps=0,
            stub_ladder_purity=0.0,
            transposed_period_axis=True,
        ),
        _result(14.5),
    )
    assert out.claims == (LEASE,)


def test_seat_refuses_the_transposed_arm_below_its_floor() -> None:
    out = _seat(
        _geometry(
            year_span=0,
            period_steps=0,
            stub_ladder_purity=0.0,
            transposed_period_axis=True,
        ),
        _result(13.0),
    )
    assert out.claims == ()
