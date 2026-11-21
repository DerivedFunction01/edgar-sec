"""Stock comp separator parameter table (TEST_STOCK_COMP_SEPARATOR).
The priced legs as built: span_ge_5 and the C2 composition
(seat_bound, warrant_vocab, available_pool) read one candidate;
assign_other reads the filing's candidate set.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class StockCompSeparatorLeg:
    """One priced leg: kind, scope, and parameter. Kinds: span,
    seat_bound, warrant, available (claim-local); assign_other
    (set-level joint assignment anchored on a determined seat)."""

    leg_id: str
    kind: str
    scope: str
    limit: float = 0.0
    anchor_family: str = ""


@dataclass(frozen=True)
class StockCompSeparatorSpec:
    """One family's separator: the ordered legs as priced — the
    span and C2 claim-local legs over one candidate, then the
    set-level assign_other over the filing's candidate set."""

    family: str
    legs: tuple[StockCompSeparatorLeg, ...]


STOCK_COMP_SEPARATOR_SPECS = {
    "stock_comp_rollforward": StockCompSeparatorSpec(
        family="stock_comp_rollforward",
        legs=(
            StockCompSeparatorLeg("span_ge_5", "span", "claim-local", limit=5),
            StockCompSeparatorLeg("seat_bound", "seat_bound", "claim-local", limit=3),
            StockCompSeparatorLeg("warrant_vocab", "warrant", "claim-local"),
            StockCompSeparatorLeg("available_pool", "available", "claim-local"),
            StockCompSeparatorLeg(
                "assign_other",
                "assign_other",
                "set-level",
                anchor_family="valuation_model_assumptions",
            ),
        ),
    ),
}
