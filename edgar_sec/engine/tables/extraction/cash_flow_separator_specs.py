"""Cash-flow cascade parameter table (TEST_CASH_FLOW_SEPARATOR).
The Composition B claim-local leg set as priced, minus the legs
the s7 pricing retired: rows_le_12 and
core_absent:cash_reconciliation (provenance: PROV_CASH_FLOW_CASCADE).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CashFlowSeparatorLeg:
    """One cascade leg: kind, scope, and parameter."""

    leg_id: str
    kind: str
    scope: str
    term: str = ""
    limit: float = 0.0


@dataclass(frozen=True)
class CashFlowSeparatorSpec:
    """One family's cascade: the ordered legs plus the core
    section the cascade was priced around."""

    family: str
    legs: tuple[CashFlowSeparatorLeg, ...]
    core_section: str


CASH_FLOW_SEPARATOR_SPECS = {
    "cash_flow": CashFlowSeparatorSpec(
        family="cash_flow",
        legs=(
            CashFlowSeparatorLeg("hdr:value", "header", "claim-local", term="value"),
        ),
        core_section="cash_reconciliation",
    ),
}
