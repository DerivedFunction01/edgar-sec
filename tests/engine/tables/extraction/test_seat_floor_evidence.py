"""Seat-at-floor channel: registry data, seat act, claim state."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.competition import CLAIM_FLOOR, compete
from edgar_sec.engine.tables.extraction.form_test_specs import (
    FORM_TEST_SPECS,
    SEAT_FLOOR_SPECS as FACADE_SEAT_FLOOR_SPECS,
)
from edgar_sec.engine.tables.extraction.form_tests import FormTestOutcome
from edgar_sec.engine.tables.extraction.geometry_scoring import (
    ClaimEvidence,
    FamilyScore,
)
from edgar_sec.engine.tables.extraction.geometry_text import GeometryText
from edgar_sec.engine.tables.extraction.profiles import (
    PROV_SEAT_FLOOR_PRICING,
    TEST_CREDIT_LOSSES_EVIDENCE,
    TEST_MEASURE_SET,
)
from edgar_sec.engine.tables.extraction.seat_floor_evidence import apply_seat_floor
from edgar_sec.engine.tables.extraction.seat_floor_specs import SEAT_FLOOR_SPECS

FAMILIES = (
    "credit_losses_rollforward",
    "goodwill_rollforward",
    "aro_rollforward",
    "restructuring",
    "warranty",
    "shares_purchased",
    "combined_operations_ci",
)


def _outcome(family, test_id, kind, passed=True):
    return FormTestOutcome(family, test_id, kind, passed, True, 0, 3.0, "seat detail")


def _credit_outcome(passed=True):
    return _outcome(
        "credit_losses_rollforward",
        "credit_losses_rollforward_evidence",
        TEST_CREDIT_LOSSES_EVIDENCE,
        passed,
    )


def test_registry_declares_the_seven_families():
    assert tuple(SEAT_FLOOR_SPECS) == FAMILIES
    assert FACADE_SEAT_FLOOR_SPECS is SEAT_FLOOR_SPECS
    declared = {(s.family, s.test_id): s for s in FORM_TEST_SPECS}
    for family, spec in SEAT_FLOOR_SPECS.items():
        assert spec.family == family
        assert spec.provenance == PROV_SEAT_FLOOR_PRICING
        for test_id in spec.test_ids:
            assert declared[(family, test_id)].points == 3.0


def test_passed_seat_test_creates_score_at_floor():
    geometry = GeometryText(form_tests=(_credit_outcome(),))
    claims: list[str] = []
    scores = apply_seat_floor(geometry, {}, claims, {}, floor=CLAIM_FLOOR)
    assert claims == ["credit_losses_rollforward"]
    seated = scores["credit_losses_rollforward"]
    assert seated.total == CLAIM_FLOOR
    assert seated.by_channel == {"gate": CLAIM_FLOOR}
    assert seated.evidence == (ClaimEvidence("gate", "seat detail", CLAIM_FLOOR),)


def test_below_floor_score_is_lifted():
    prior = FamilyScore(
        "credit_losses_rollforward",
        3.0,
        {"form": 3.0},
        (ClaimEvidence("form", "scored", 3.0),),
    )
    geometry = GeometryText(form_tests=(_credit_outcome(),))
    claims: list[str] = []
    scores = apply_seat_floor(
        geometry, {"credit_losses_rollforward": prior}, claims, {}, floor=CLAIM_FLOOR
    )
    seated = scores["credit_losses_rollforward"]
    assert seated.total == CLAIM_FLOOR
    assert seated.by_channel == {"form": 3.0, "gate": CLAIM_FLOOR - 3.0}
    assert seated.evidence[-1] == ClaimEvidence(
        "gate", "seat detail", CLAIM_FLOOR - 3.0
    )
    assert claims == ["credit_losses_rollforward"]


def test_score_at_floor_is_claimed_without_change():
    prior = FamilyScore("combined_operations_ci", 6.0, {"form": 6.0}, ())
    outcome = _outcome(
        "combined_operations_ci",
        "combined_operations_ci_joint_measure_set",
        TEST_MEASURE_SET,
    )
    geometry = GeometryText(form_tests=(outcome,))
    claims: list[str] = []
    scores = apply_seat_floor(
        geometry, {"combined_operations_ci": prior}, claims, {}, floor=CLAIM_FLOOR
    )
    assert scores["combined_operations_ci"] is prior
    assert claims == ["combined_operations_ci"]


def test_unpassed_outcome_never_seats():
    geometry = GeometryText(form_tests=(_credit_outcome(passed=False),))
    claims: list[str] = []
    scores = apply_seat_floor(geometry, {}, claims, {}, floor=CLAIM_FLOOR)
    assert claims == [] and scores == {}


def test_hard_vetoed_family_never_seats():
    geometry = GeometryText(form_tests=(_credit_outcome(),))
    claims: list[str] = []
    scores = apply_seat_floor(
        geometry, {}, claims, {"credit_losses_rollforward": "term"}, floor=CLAIM_FLOOR
    )
    assert claims == [] and scores == {}


def test_already_claimed_family_not_repeated():
    geometry = GeometryText(form_tests=(_credit_outcome(),))
    claims = ["credit_losses_rollforward"]
    scores = apply_seat_floor(geometry, {}, claims, {}, floor=CLAIM_FLOOR)
    assert claims == ["credit_losses_rollforward"] and scores == {}


def test_foreign_family_outcome_never_seats():
    outcome = _outcome(
        "pension", "credit_losses_rollforward_evidence", TEST_CREDIT_LOSSES_EVIDENCE
    )
    geometry = GeometryText(form_tests=(outcome,))
    claims: list[str] = []
    scores = apply_seat_floor(geometry, {}, claims, {}, floor=CLAIM_FLOOR)
    assert claims == [] and scores == {}


def test_compete_seats_family_with_claimed_state():
    geometry = GeometryText(form_tests=(_credit_outcome(),))
    result = compete(geometry)
    assert result.claims == ("credit_losses_rollforward",)
    group = next(g for g in result.groups if g.family == "credit_losses_rollforward")
    assert group.state == "claimed"
    assert group.score == CLAIM_FLOOR
