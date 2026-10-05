"""Contract tests for the cover checkbox models."""

from __future__ import annotations

from edgar_sec.engine.forms.cover.checkmarks.models import (
    DEFAULT_PENALTY_SCORER,
    CheckboxCandidate,
    ConstraintViolation,
    CoverCheckmarkResult,
    HypothesisScore,
    InferenceStatus,
    PenaltyScorer,
)


def test_inference_status_covers_every_outcome() -> None:
    assert {status.value for status in InferenceStatus} == {
        "not_applicable",
        "absent",
        "unresolved",
        "resolved",
    }


def test_candidate_known_state_reads_the_source_token() -> None:
    assert CheckboxCandidate("annual", "[X]", "report_period").known_state == "checked"
    assert (
        CheckboxCandidate("annual", "[ ]", "report_period").known_state == "unchecked"
    )
    assert CheckboxCandidate("annual", "G0", "report_period").known_state is None


def test_candidate_glyph_falls_back_to_the_source_token() -> None:
    assert CheckboxCandidate("annual", "G0", "report_period").glyph == "G0"
    assert (
        CheckboxCandidate("annual", "G0", "report_period", glyph_class="●").glyph == "●"
    )


def test_violation_records_its_penalty_and_missing_keys() -> None:
    violation = ConstraintViolation(
        name="filer_primary_exactly_one",
        penalty=1000,
        reason="count is 0",
        missing=("laf",),
    )

    assert violation.missing == ("laf",)


def test_result_defaults_to_no_decisions_or_evidence() -> None:
    result = CoverCheckmarkResult(status=InferenceStatus.ABSENT)

    assert result.decisions == ()
    assert result.penalty is None
    assert result.hypotheses == ()


def test_hypothesis_score_carries_assignment_and_satisfied_tiers() -> None:
    score = HypothesisScore(
        assignment=(("G0", "checked"),),
        penalty=0,
        violations=(),
        satisfied=("filer_primary_exactly_one",),
        states=(("large_accelerated_filer", "checked"),),
    )

    assert score.assignment == (("G0", "checked"),)


def test_penalty_scorer_weights_are_readable_by_name() -> None:
    assert PenaltyScorer().weight("binary_xor") == 1000
    assert DEFAULT_PENALTY_SCORER.weight("direct_state") == 5000
    assert PenaltyScorer(binary_xor=5).weight("binary_xor") == 5
