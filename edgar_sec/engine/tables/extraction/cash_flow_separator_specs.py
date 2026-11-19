"""Cash-flow cascade parameter table (TEST_CASH_FLOW_SEPARATOR).
The Composition B leg set as built, in firing order: claim-local
legs read the candidate, the set-level leg reads the filing's
complete candidate set (provenance: PROV_CASH_FLOW_CASCADE).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CashFlowSeparatorLeg:
    """One cascade leg: kind, scope, and parameter. Kinds: rows,
    header, core_absent (claim-local); winner_take_all (set-level
    joint assignment over the filing's candidate set)."""

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
            CashFlowSeparatorLeg(
                "core_absent:cash_reconciliation", "core_absent", "claim-local"
            ),
            CashFlowSeparatorLeg("winner_take_all", "winner_take_all", "set-level"),
        ),
        core_section="cash_reconciliation",
    ),
}
