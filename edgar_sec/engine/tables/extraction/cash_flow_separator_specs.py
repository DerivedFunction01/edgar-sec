"""Cash-flow cascade parameter table (TEST_CASH_FLOW_SEPARATOR).
The priced Composition B leg set as data, in firing order:
claim-local legs read the candidate, set-level legs read the
filing's complete candidate set (provenance: PROV_CASH_FLOW_CASCADE).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CashFlowSeparatorLeg:
    """One priced cascade leg: its kind, scope, and parameter.
    Kinds: rows (grid lines at most limit), header (key),
    core_absent (the family's core section absent), gold_route
    and winner_take_all (set-level joint assignment)."""

    leg_id: str
    kind: str
    scope: str
    term: str = ""
    limit: float = 0.0


@dataclass(frozen=True)
class CashFlowSeparatorSpec:
    """One family's cascade: the ordered legs plus the core.
    The core is the determined cash_reconciliation section: its
    absence is the core gate, a necessary condition at claimage."""

    family: str
    legs: tuple[CashFlowSeparatorLeg, ...]
    core_section: str


CASH_FLOW_SEPARATOR_SPECS = {
    "cash_flow": CashFlowSeparatorSpec(
        family="cash_flow",
        legs=(
            CashFlowSeparatorLeg("rows_le_12", "rows", "claim-local", limit=12),
            CashFlowSeparatorLeg("hdr:value", "header", "claim-local", term="value"),
            CashFlowSeparatorLeg("gold_route", "gold_route", "set-level"),
            CashFlowSeparatorLeg(
                "core_absent:cash_reconciliation", "core_absent", "claim-local"
            ),
            CashFlowSeparatorLeg("winner_take_all", "winner_take_all", "set-level"),
        ),
        core_section="cash_reconciliation",
    ),
}
