"""Stock comp separator parameter table (TEST_STOCK_COMP_SEPARATOR).
The priced pair as built: span_ge_5 reads the candidate's grid,
assign_other reads the filing's candidate set (provenance:
PROV_STOCK_COMP_SEPARATOR).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class StockCompSeparatorLeg:
    """One priced leg: kind, scope, and parameter. Kinds: span
    (claim-local); assign_other (set-level joint assignment
    anchored on a determined other-family seat)."""

    leg_id: str
    kind: str
    scope: str
    limit: float = 0.0
    anchor_family: str = ""


@dataclass(frozen=True)
class StockCompSeparatorSpec:
    """One family's separator: the ordered legs as priced.
    span_ge_5 refuses a grant listing whose grid spans five or
    more distinct years; assign_other refuses a claim whose
    geometry a determined other-family seat has seated."""

    family: str
    legs: tuple[StockCompSeparatorLeg, ...]


STOCK_COMP_SEPARATOR_SPECS = {
    "stock_comp_rollforward": StockCompSeparatorSpec(
        family="stock_comp_rollforward",
        legs=(
            StockCompSeparatorLeg("span_ge_5", "span", "claim-local", limit=5),
            StockCompSeparatorLeg(
                "assign_other",
                "assign_other",
                "set-level",
                anchor_family="valuation_model_assumptions",
            ),
        ),
    ),
}
