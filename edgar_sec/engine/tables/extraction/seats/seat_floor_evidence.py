"""Seat-at-floor channel: priced seat tests claim their family."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.cascade.geometry_scoring import (
    ClaimEvidence,
    FamilyScore,
)
from edgar_sec.engine.tables.extraction.seats.seat_floor_specs import SEAT_FLOOR_SPECS


def _passed_seat_outcome(form_tests, spec):
    """The family's stamped seat outcome that passed, if any."""
    for outcome in form_tests:
        if (
            outcome.family == spec.family
            and outcome.test_id in spec.test_ids
            and outcome.passed
        ):
            return outcome
    return None


def apply_seat_floor(geometry, scores, claims, hard_vetoed, *, floor):
    """Seat each registered family whose seat test passed.

    Already-claimed or hard-vetoed families never act; the
    score is created or lifted to the floor via the gate channel.
    """
    for family, spec in SEAT_FLOOR_SPECS.items():
        if family in claims or family in hard_vetoed:
            continue
        outcome = _passed_seat_outcome(geometry.form_tests, spec)
        if outcome is None:
            continue
        existing = scores.get(family)
        if existing is None or existing.total < floor:
            base = existing.total if existing is not None else 0.0
            lift = floor - base
            channels = dict(existing.by_channel) if existing is not None else {}
            channels["gate"] = channels.get("gate", 0.0) + lift
            evidence = existing.evidence if existing is not None else ()
            note = ClaimEvidence("gate", outcome.detail, lift)
            seated = FamilyScore(family, floor, channels, evidence + (note,))
            scores = {**scores, family: seated}
        claims.append(family)
    return scores
