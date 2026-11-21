"""Placement facts over a filing's own first-pass family reads.

The statement span opens at the filing's first primary-assigned
table and extends across gaps of at most two non-primary tables;
facts are per table position in the filing's geometry sequence.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core.registry import (
    PRIMARY_STATEMENT_FAMILIES,
)

GAP_TOLERANCE = 2
DEEP_NOTES_DISTANCE = 15
NEIGHBOURHOOD = 2

REGION_FRONT = "front"
REGION_STATEMENTS = "statements"
REGION_NOTES = "notes"
REGION_UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class PlacementFacts:
    """One table's placement inside its filing's geometry sequence."""

    region: str
    in_span: bool
    span_distance: int | None
    isolated: bool
    deep_notes: bool
    no_statement_cluster: bool


def statement_span(families: tuple[str, ...]) -> tuple[int, int] | None:
    """The (start, end) positions of the statement run, or None.
    The first primary table opens the run; it extends across
    gaps of at most GAP_TOLERANCE non-primary tables."""
    primaries = [
        i for i, family in enumerate(families) if family in PRIMARY_STATEMENT_FAMILIES
    ]
    if not primaries:
        return None
    start = end = primaries[0]
    for position in primaries[1:]:
        if position - end - 1 <= GAP_TOLERANCE:
            end = position
        else:
            break
    return start, end


def placement_facts(families: tuple[str, ...], position: int) -> PlacementFacts:
    """Placement facts for the table at position in the sequence."""
    span = statement_span(families)
    primaries = [
        i for i, family in enumerate(families) if family in PRIMARY_STATEMENT_FAMILIES
    ]
    isolated = not any(
        1 <= abs(position - primary) <= NEIGHBOURHOOD for primary in primaries
    )
    if span is None:
        return PlacementFacts(REGION_UNKNOWN, False, None, isolated, False, True)
    start, end = span
    if position < start:
        region, in_span, distance = REGION_FRONT, False, position - start
    elif position > end:
        region, in_span, distance = REGION_NOTES, False, position - end
    else:
        region, in_span, distance = REGION_STATEMENTS, True, 0
    return PlacementFacts(
        region,
        in_span,
        distance,
        isolated,
        distance >= DEEP_NOTES_DISTANCE,
        False,
    )
