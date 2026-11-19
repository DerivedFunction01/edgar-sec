"""Cash-flow cascade evidence (TEST_CASH_FLOW_SEPARATOR).
Evaluates the priced Composition B claim-local legs over one
table's grid: a cash_flow claim is refused when any leg fires.
The leg semantics are the cascade pricing's, as priced.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.cash_flow_separator_specs import (
    CASH_FLOW_SEPARATOR_SPECS,
    CashFlowSeparatorSpec,
)
from edgar_sec.engine.tables.extraction.core_form_evidence import (
    failing_core_form_outcome as fired_separator_outcome,
)
from edgar_sec.engine.tables.extraction.pension_routed_evidence import (
    norm as token_norm,
    stub_key,
)
from edgar_sec.engine.tables.extraction.pension_routed_specs import (
    HEADER_STOP_TOKENS,
)
from edgar_sec.engine.tables.extraction.primary_gate import section_presence

__all__ = [
    "CashFlowSeparatorText",
    "CashFlowSeparatorVerdict",
    "evaluate_cash_flow_separator",
    "evaluate_form_test_cash_flow_separator",
    "fired_separator_outcome",
    "stub_key",
    "token_norm",
]


class CashFlowSeparatorText:
    """One table's grid as the cascade reads it: lines of cells."""

    def __init__(self, table_text: str = ""):
        lines = [ln for ln in (table_text or "").split("\n") if ln.strip()]
        self.rows = [[c.strip() for c in ln.split("|")] for ln in lines]
        self.stubs = [row[0] for row in self.rows if row and row[0]]
        self.headers = [c for row in self.rows[:3] for c in row if c]

    @classmethod
    def from_rows(cls, rows) -> "CashFlowSeparatorText":
        """Grid text from raw context rows (production surface)."""
        table_text = "\n".join(" | ".join(str(c) for c in row) for row in rows)
        return cls(table_text)

    @classmethod
    def from_packet(cls, packet) -> "CashFlowSeparatorText":
        """Grid text from a census packet (priced population)."""
        return cls(packet.get("table_text") or "")


@dataclass(frozen=True)
class CashFlowSeparatorVerdict:
    """The cascade verdict for one table: fired legs, if any."""

    fired: bool
    evaluable: bool
    legs: tuple[str, ...]
    detail: str


def evaluate_cash_flow_separator(
    text: CashFlowSeparatorText, spec: CashFlowSeparatorSpec
) -> CashFlowSeparatorVerdict:
    """Evaluate one grid against the family's priced cascade."""
    if not text.rows:
        return CashFlowSeparatorVerdict(
            False, False, (), "separator unevaluable: no grid rows"
        )
    header_keys = set()
    for header in text.headers:
        key = stub_key(header)
        if len(key) >= 3:
            header_keys.add(key)
        for token in token_norm(header).split():
            if (
                len(token) > 2
                and not token.isdigit()
                and token not in HEADER_STOP_TOKENS
            ):
                header_keys.add(token)
    core_present = section_presence(text.stubs, spec.family)[spec.core_section]
    fired: list[str] = []
    for leg in spec.legs:
        if leg.scope != "claim-local":
            continue
        if leg.kind == "rows" and len(text.rows) <= leg.limit:
            fired.append(leg.leg_id)
        elif leg.kind == "header" and leg.term in header_keys:
            fired.append(leg.leg_id)
        elif leg.kind == "core_absent" and not core_present:
            fired.append(leg.leg_id)
    if fired:
        detail = "separator fired: " + ", ".join(fired)
        return CashFlowSeparatorVerdict(True, True, tuple(fired), detail)
    return CashFlowSeparatorVerdict(False, True, (), "separator clear")


# ---------------- production wiring (stage adapter + gate) ----------------


def evaluate_form_test_cash_flow_separator(table, spec):
    """Stage adapter: evaluate the declared cascade over a table."""
    gate_spec = CASH_FLOW_SEPARATOR_SPECS.get(spec.family)
    if gate_spec is None:
        return CashFlowSeparatorVerdict(
            False, False, (), "no separator spec for family"
        )
    text = CashFlowSeparatorText.from_rows(table.context.rows)
    return evaluate_cash_flow_separator(text, gate_spec)
