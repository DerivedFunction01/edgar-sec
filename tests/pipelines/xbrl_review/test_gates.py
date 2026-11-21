"""Tests for XBRL review promotion gate-evidence validation."""

import pytest

from edgar_sec.pipelines.xbrl_review.gates import validate_gate_evidence

_PASSING = {
    "census": {"passed": True},
    "pair_gate": {"total": 18, "passed": 18},
    "battery": {
        "total": 188,
        "passed": 188,
        "failure_ids": [],
    },
}


def test_validate_gate_evidence_accepts_adjudicated_baseline() -> None:
    """Verify the pinned baseline evidence passes validation."""
    validate_gate_evidence(_PASSING)


def test_validate_gate_evidence_requires_evidence() -> None:
    """Verify missing evidence refuses promotion."""
    with pytest.raises(ValueError, match="requires gate evidence"):
        validate_gate_evidence(None)


def test_validate_gate_evidence_refuses_failing_census() -> None:
    """Verify a failing census refuses promotion."""
    evidence = {**_PASSING, "census": {"passed": False}}
    with pytest.raises(ValueError, match="census"):
        validate_gate_evidence(evidence)


def test_validate_gate_evidence_refuses_failing_pair_gate() -> None:
    """Verify a short pair gate refuses promotion."""
    evidence = {**_PASSING, "pair_gate": {"total": 18, "passed": 17}}
    with pytest.raises(ValueError, match="pair gate"):
        validate_gate_evidence(evidence)


def test_validate_gate_evidence_refuses_unadjudicated_battery_failure() -> None:
    """Verify a battery failure beyond the adjudicated one refuses promotion."""
    evidence = {
        **_PASSING,
        "battery": {
            "total": 188,
            "passed": 187,
            "failure_ids": ["some-other-entry"],
        },
    }
    with pytest.raises(ValueError, match="battery"):
        validate_gate_evidence(evidence)
