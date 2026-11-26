"""Balance-sheet separator evidence (TEST_BALANCE_SHEET_SEPARATOR).
Evaluates the priced separator legs over one table's grid: a
balance_sheet claim is refused when any leg fires. The leg
semantics are the imposter census derivation's, as priced.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.separators.balance_sheet_separator_specs import (
    BALANCE_SHEET_SEPARATOR_SPECS,
    BalanceSheetSeparatorSpec,
)
from edgar_sec.engine.tables.extraction.evidence.form.core_form_evidence import (
    failing_core_form_outcome as fired_separator_outcome,
)
from edgar_sec.engine.tables.extraction.pension.pension_routed_evidence import (
    header_keys,
    norm as token_norm,
    stub_key,
)
from edgar_sec.engine.tables.extraction.pension.pension_routed_specs import (
    HEADER_STOP_TOKENS,
    MONTH_TOKENS,
)
from edgar_sec.engine.tables.numeric_cells import DIGIT_RE, WRAPPED_NUMERIC_CELL_RE
from edgar_sec.foundation.text.date_patterns import YEAR_TOKEN_SEARCH_RE
from edgar_sec.foundation.text.patterns import RE_NON_ALNUM, RE_WHITESPACE


class BalanceSheetSeparatorText:
    """One table's grid as the separator reads it: lines of cells."""

    def __init__(self, table_text: str = ""):
        lines = [ln for ln in (table_text or "").split("\n") if ln.strip()]
        self.rows = [[c.strip() for c in ln.split("|")] for ln in lines]
        self.stubs = [row[0] for row in self.rows if row and row[0]]
        self.headers = [c for row in self.rows[:3] for c in row if c]

    @classmethod
    def from_rows(cls, rows) -> "BalanceSheetSeparatorText":
        """Grid text from raw context rows (production surface)."""
        table_text = "\n".join(" | ".join(str(c) for c in row) for row in rows)
        return cls(table_text)

    @classmethod
    def from_packet(cls, packet) -> "BalanceSheetSeparatorText":
        """Grid text from a census packet (priced population)."""
        return cls(packet.get("table_text") or "")


@dataclass(frozen=True)
class BalanceSheetSeparatorVerdict:
    """The separator verdict for one table: fired legs, if any."""

    fired: bool
    evaluable: bool
    legs: tuple[str, ...]
    detail: str


def _numeric_share(rows) -> float:
    """The priced numeric share: numeric cells over non-empty cells."""
    numeric = total = 0
    for row in rows:
        for cell in row:
            if not cell:
                continue
            total += 1
            if WRAPPED_NUMERIC_CELL_RE.fullmatch(cell.replace("$", "").strip()) or (
                DIGIT_RE.search(cell) and WRAPPED_NUMERIC_CELL_RE.search(cell)
            ):
                numeric += 1
    return round(numeric / total, 3) if total else 0.0


def evaluate_balance_sheet_separator(
    text: BalanceSheetSeparatorText, spec: BalanceSheetSeparatorSpec
) -> BalanceSheetSeparatorVerdict:
    """Evaluate one grid against the family's priced separator."""
    if not text.rows:
        return BalanceSheetSeparatorVerdict(
            False, False, (), "separator unevaluable: no grid rows"
        )
    stub_keys = {k for k in (stub_key(s) for s in text.stubs) if len(k) >= 3}
    hdr_keys = header_keys(tuple(text.headers))
    year_count = len(YEAR_TOKEN_SEARCH_RE.findall(" ".join(text.headers)))
    numeric_share = _numeric_share(text.rows)
    closing_pair = (
        "total assets" in stub_keys
        and any(k.startswith("total liabilities") for k in stub_keys)
        and (
            any(k in stub_keys for k in spec.equity_total_keys)
            or any(k.startswith("total liabilities and") for k in stub_keys)
        )
    )
    fired: list[str] = []
    for leg in spec.legs:
        if closing_pair and leg.leg_id in spec.closing_pair_exempt_legs:
            continue
        if leg.kind == "rows" and len(text.rows) <= leg.limit:
            fired.append(leg.leg_id)
        elif leg.kind == "years" and year_count >= leg.limit:
            fired.append(leg.leg_id)
        elif leg.kind == "header" and leg.term in hdr_keys:
            fired.append(leg.leg_id)
        elif leg.kind == "stub" and leg.term in stub_keys:
            fired.append(leg.leg_id)
        elif leg.kind == "numshare" and numeric_share < leg.limit:
            fired.append(leg.leg_id)
    if any(phrase in stub_keys for phrase in spec.accrued_stub_phrases):
        fired.append("accrued_stub")
    if fired:
        detail = "separator fired: " + ", ".join(fired)
        return BalanceSheetSeparatorVerdict(True, True, tuple(fired), detail)
    return BalanceSheetSeparatorVerdict(False, True, (), "separator clear")


# ---------------- production wiring (stage adapter + gate) ----------------


def evaluate_form_test_balance_sheet_separator(table, spec):
    """Stage adapter: evaluate the declared separator over a table."""
    gate_spec = BALANCE_SHEET_SEPARATOR_SPECS.get(spec.family)
    if gate_spec is None:
        return BalanceSheetSeparatorVerdict(
            False, False, (), "no separator spec for family"
        )
    text = BalanceSheetSeparatorText.from_rows(table.context.rows)
    return evaluate_balance_sheet_separator(text, gate_spec)
