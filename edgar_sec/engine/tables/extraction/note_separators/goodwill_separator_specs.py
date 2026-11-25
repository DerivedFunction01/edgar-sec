"""Goodwill separator parameter table (TEST_GOODWILL_SEPARATOR).
The priced composition as built: the allocation-form conjunction,
claim-local over the candidate's grid (provenance:
PROV_GOODWILL_SEPARATOR)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class GoodwillSeparatorLeg:
    """One priced leg: kind, scope, and parameter. Kinds:
    allocation_columns, goodwill_acquired_line, no_bookend_walk
    (all claim-local); the separator fires on the conjunction."""

    leg_id: str
    kind: str
    scope: str
    limit: float = 0.0


@dataclass(frozen=True)
class GoodwillSeparatorSpec:
    """One family's separator: the priced legs, held conjunctively —
    the preliminary-side and final allocation columns, a goodwill
    line among the acquired assets, no goodwill bookend walk."""

    family: str
    legs: tuple[GoodwillSeparatorLeg, ...]


GOODWILL_SEPARATOR_SPECS = {
    "goodwill_rollforward": GoodwillSeparatorSpec(
        family="goodwill_rollforward",
        legs=(
            GoodwillSeparatorLeg("alloc_columns", "allocation_columns", "claim-local"),
            GoodwillSeparatorLeg(
                "goodwill_acquired_line", "goodwill_acquired_line", "claim-local"
            ),
            GoodwillSeparatorLeg("no_bookend_walk", "no_bookend_walk", "claim-local"),
        ),
    ),
}
