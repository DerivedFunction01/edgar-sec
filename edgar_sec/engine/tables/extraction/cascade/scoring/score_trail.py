"""Score-trail edits for the signature competition: seating a
family at the claim floor and appending zero-point notes.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    ClaimEvidence,
    FamilyScore,
)


def seat_at_floor(
    scores: dict[str, FamilyScore], family: str, detail: str, floor: float
) -> dict[str, FamilyScore]:
    """Seat one family at the claim floor via the gate channel."""
    existing = scores.get(family)
    if existing is not None and existing.total >= floor:
        return scores
    base = existing.total if existing is not None else 0.0
    lift = floor - base
    channels = dict(existing.by_channel) if existing is not None else {}
    channels["gate"] = channels.get("gate", 0.0) + lift
    evidence = existing.evidence if existing is not None else ()
    note = ClaimEvidence("gate", detail, lift)
    seated = FamilyScore(family, floor, channels, evidence + (note,))
    return {**scores, family: seated}


def append_note(
    scores: dict[str, FamilyScore], family: str, channel: str, detail: str
) -> dict[str, FamilyScore]:
    """Append a zero-point note to one family's trail."""
    score = scores[family]
    return {
        **scores,
        family: FamilyScore(
            family,
            score.total,
            dict(score.by_channel),
            score.evidence + (ClaimEvidence(channel, detail, 0.0),),
        ),
    }
