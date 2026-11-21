"""Input-class seat kind: the priced rule's specimen shapes.
Pins transcribe the R18 pass's priced leg definitions.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.cascade.competition import CLAIM_FLOOR
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    ClaimEvidence,
    FamilyScore,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.evidence.form.input_class_evidence import (
    apply_input_class_seat,
    input_class_evidence_for_geometry,
)
from edgar_sec.engine.tables.extraction.specs.input_class_specs import (
    INPUT_CLASS_EVIDENCE_SPECS,
)
from edgar_sec.engine.tables.extraction.core.subjects.profiles import (
    PROV_R18_SEAT_PRICING,
)

FAMILY = "valuation_model_assumptions"
SPEC = INPUT_CLASS_EVIDENCE_SPECS[FAMILY]
TOKENS = (
    "volatility",
    "risk-free",
    "risk free",
    "dividend",
    "expected term",
    "expected life",
    "forfeiture",
    "exercise price",
    "stock price",
    "share price",
    "interest rate",
    "discount rate",
    "growth rate",
    "royalty",
    "weighted average cost",
    "correlation",
    "expected return",
    "illiquidity",
    "marketability",
    "expected dividend",
)
SEATING_TEXT = "volatility dividend royalty"


def seat(claims, scores, hard_vetoed=None, grid_text=SEATING_TEXT):
    return apply_input_class_seat(
        GeometryText(grid_text=grid_text),
        claims,
        scores,
        hard_vetoed or {},
        floor=CLAIM_FLOOR,
        score_type=FamilyScore,
        evidence_type=ClaimEvidence,
    )


def test_spec_registered_for_family():
    assert SPEC.family == FAMILY
    assert SPEC.min_classes == 3
    assert SPEC.provenance == PROV_R18_SEAT_PRICING


def test_spec_tokens_verbatim():
    assert SPEC.input_classes == TOKENS


def test_threshold_boundary():
    below = input_class_evidence_for_geometry(
        GeometryText(grid_text="volatility dividend")
    )
    assert not below.admitted
    assert below.classes_found == ("volatility", "dividend")
    at = input_class_evidence_for_geometry(GeometryText(grid_text=SEATING_TEXT))
    assert at.admitted
    assert at.classes_found == ("volatility", "dividend", "royalty")


def test_overlap_counting():
    verdict = input_class_evidence_for_geometry(
        GeometryText(grid_text="expected dividend volatility")
    )
    assert verdict.classes_found == ("volatility", "dividend", "expected dividend")
    assert verdict.admitted


def test_hyphen_and_space_tokens_are_distinct():
    hyphen = input_class_evidence_for_geometry(GeometryText(grid_text="risk-free"))
    assert hyphen.classes_found == ("risk-free",)
    space = input_class_evidence_for_geometry(GeometryText(grid_text="risk free"))
    assert space.classes_found == ("risk free",)


def test_refused_terms_not_inherited():
    assert not hasattr(SPEC, "refused_terms")
    verdict = input_class_evidence_for_geometry(
        GeometryText(grid_text="level 3 unobservable " + SEATING_TEXT)
    )
    assert verdict.admitted


def test_grid_text_only_surface():
    framed = GeometryText(
        caption=SEATING_TEXT,
        stubs=("expected term", "expected life"),
        leadin="forfeiture rate",
        grid_text="",
    )
    assert not input_class_evidence_for_geometry(framed).admitted


def test_seat_creates_claim_at_floor():
    claims, scores = seat([], {})
    assert claims == [FAMILY]
    score = scores[FAMILY]
    assert score.total == CLAIM_FLOOR
    assert score.by_channel == {"gate": CLAIM_FLOOR}
    assert score.evidence[-1].channel == "gate"
    assert score.evidence[-1].points == CLAIM_FLOOR


def test_seat_lifts_existing_score():
    prior = ClaimEvidence("stub", "stub mass", 2.0)
    existing = FamilyScore(FAMILY, 2.0, {"stub": 2.0}, (prior,))
    claims, scores = seat([], {FAMILY: existing})
    assert claims == [FAMILY]
    score = scores[FAMILY]
    assert score.total == CLAIM_FLOOR
    assert score.by_channel == {"stub": 2.0, "gate": CLAIM_FLOOR - 2.0}
    assert score.evidence[0] == prior
    assert score.evidence[-1].channel == "gate"


def test_seat_beside_existing_claim():
    other = FamilyScore("pension", 9.0, {"stub": 9.0}, ())
    claims, scores = seat(["pension"], {"pension": other})
    assert claims == ["pension", FAMILY]
    assert scores["pension"] == other


def test_no_act_when_already_claimed():
    existing = FamilyScore(FAMILY, 7.0, {"stub": 7.0}, ())
    claims, scores = seat([FAMILY], {FAMILY: existing})
    assert claims == [FAMILY]
    assert scores[FAMILY] == existing


def test_no_seat_below_threshold():
    claims, scores = seat([], {}, grid_text="volatility dividend")
    assert claims == []
    assert scores == {}


def test_no_seat_when_hard_vetoed():
    claims, scores = seat([], {}, hard_vetoed={FAMILY: "some term"})
    assert claims == []
    assert scores == {}
