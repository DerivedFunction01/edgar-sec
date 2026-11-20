"""Deferred tax separator evidence (TEST_DEFERRED_TAX_SEPARATOR).
Evaluates the priced composition over one table's grid: a
deferred_tax claim is refused when the determined deferred-tax
core is absent and a shares stub or a geography stub holds.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core_form_evidence import (
    failing_core_form_outcome as fired_separator_outcome,
)
from edgar_sec.engine.tables.extraction.deferred_tax_separator_specs import (
    DEFERRED_TAX_SEPARATOR_SPECS,
    DeferredTaxSeparatorSpec,
)
from edgar_sec.engine.tables.extraction.tax_reconciliation_separator_evidence import (
    norm_phrase,
)

__all__ = [
    "DeferredTaxSeparatorText",
    "DeferredTaxSeparatorVerdict",
    "deferred_core_present",
    "evaluate_deferred_tax_separator",
    "evaluate_form_test_deferred_tax_separator",
    "fired_separator_outcome",
    "geo_stub",
    "shares_stub",
]

LEG_CORE_ABSENT = "det_core_absent"
LEG_SHARES = "shares_stub"
LEG_GEO = "geo_stub"


class DeferredTaxSeparatorText:
    """One table's grid as the separator reads it: rows of cells."""

    def __init__(self, table_text: str = "", caption_stack=()):
        self.table_text = table_text or ""
        self.caption_stack = list(caption_stack or [])
        lines = []
        for ln in self.table_text.split("\n"):
            cells = [c.strip() for c in ln.split("|")]
            if any(cells):
                lines.append(cells)
        self.rows = lines
        self.stub_phrases = [
            norm_phrase(next((c for c in cells if c), "")) for cells in lines
        ]

    @classmethod
    def from_rows(cls, rows, caption_stack=()) -> "DeferredTaxSeparatorText":
        """Grid text from raw context rows (production surface)."""
        table_text = "\n".join(" | ".join(str(c) for c in row) for row in rows)
        return cls(table_text, caption_stack)

    @classmethod
    def from_packet(cls, packet) -> "DeferredTaxSeparatorText":
        """Grid text from a census packet (priced population)."""
        return cls(
            packet.get("table_text") or "", packet.get("caption_stack") or []
        )


@dataclass(frozen=True)
class DeferredTaxSeparatorVerdict:
    """The separator verdict for one table: fired legs, if any."""

    fired: bool
    evaluable: bool
    legs: tuple[str, ...]
    detail: str


def shares_stub(text: DeferredTaxSeparatorText, spec: DeferredTaxSeparatorSpec) -> bool:
    """Any row stub naming shares (the ESOP-table content leg)."""
    for cells in text.rows:
        first = next((c for c in cells if c), "")
        if spec.shares_token in first.lower():
            return True
    return False


def geo_stub(text: DeferredTaxSeparatorText, spec: DeferredTaxSeparatorSpec) -> bool:
    """Any stub phrase naming a geography (the by-geography leg)."""
    return any(
        token in phrase for phrase in text.stub_phrases for token in spec.geo_tokens
    )


def deferred_core_present(text: DeferredTaxSeparatorText) -> bool:
    """The determined deferred-tax core: the subject over caption
    plus grid, a deferred-tax-asset or net leg, and a liability or
    net leg, read over the normalized stub phrases."""
    joined_all = (" ".join(text.caption_stack) + " " + text.table_text).lower()
    subject = "deferred tax" in joined_all or "deferred income tax" in joined_all
    dta_total = any("deferred tax asset" in ph for ph in text.stub_phrases)
    dtl_total = any("deferred tax liabilit" in ph for ph in text.stub_phrases)
    dt_net = any("net deferred" in ph for ph in text.stub_phrases)
    return bool(subject and (dta_total or dt_net) and (dtl_total or dt_net))


def evaluate_deferred_tax_separator(
    text: DeferredTaxSeparatorText, spec: DeferredTaxSeparatorSpec
) -> DeferredTaxSeparatorVerdict:
    """Evaluate one grid against the family's priced composition."""
    if not text.rows:
        return DeferredTaxSeparatorVerdict(
            False, False, (), "separator unevaluable: no grid rows"
        )
    if deferred_core_present(text):
        return DeferredTaxSeparatorVerdict(False, True, (), "separator clear")
    legs = [LEG_CORE_ABSENT]
    if shares_stub(text, spec):
        legs.append(LEG_SHARES)
    if geo_stub(text, spec):
        legs.append(LEG_GEO)
    if len(legs) >= 2:
        detail = "separator fired: " + ", ".join(legs)
        return DeferredTaxSeparatorVerdict(True, True, tuple(legs), detail)
    return DeferredTaxSeparatorVerdict(False, True, (), "separator clear")


# ---------------- production wiring (stage adapter) ----------------


def evaluate_form_test_deferred_tax_separator(table, spec):
    """Stage adapter: evaluate the declared separator over a table."""
    gate_spec = DEFERRED_TAX_SEPARATOR_SPECS.get(spec.family)
    if gate_spec is None:
        return DeferredTaxSeparatorVerdict(
            False, False, (), "no separator spec for family"
        )
    text = DeferredTaxSeparatorText.from_rows(
        table.context.rows, table.context.caption_stack
    )
    return evaluate_deferred_tax_separator(text, gate_spec)
