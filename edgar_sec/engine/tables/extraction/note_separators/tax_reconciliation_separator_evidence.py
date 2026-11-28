"""Tax reconciliation separator evidence (TEST_TAX_RECONCILIATION_SEPARATOR).
Evaluates the priced conjunction over one table's grid: a
tax_reconciliation claim is refused when the determined rate core
is absent, movement is zero, and the grid has at most eight rows.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from edgar_sec.engine.forms.common.values.numbers import SCHEMA_PERCENT_RE
from edgar_sec.engine.tables.extraction.evidence.form.core_form_evidence import (
    failing_core_form_outcome as fired_separator_outcome,
)
from edgar_sec.engine.tables.extraction.note_separators.tax_reconciliation_separator_specs import (
    MOVE_WORDS,
    TAX_RECONCILIATION_SEPARATOR_SPECS,
    TaxReconciliationSeparatorSpec,
)
from edgar_sec.foundation.text.dashes import CELL_DASHES
from edgar_sec.foundation.text.patterns import RE_WHITESPACE

__all__ = [
    "TaxReconciliationSeparatorText",
    "TaxReconciliationSeparatorVerdict",
    "evaluate_form_test_tax_reconciliation_separator",
    "evaluate_tax_reconciliation_separator",
    "fired_separator_outcome",
    "movement_nonzero",
    "norm_phrase",
    "rate_core_present",
]

_ZERO_TOKENS = CELL_DASHES | {"", "*"}
_NUM_RE = re.compile(r"^\(?\$?[\d,]+(?:\.\d+)?\)?$")
_DIGITS_RE = re.compile(r"\d+")
_NON_PHRASE_RE = re.compile(r"[^a-z# ]+")

LEG_CORE_ABSENT = "det_core_absent"
LEG_MOVE_NONZERO = "move_nonzero_le_0"
LEG_ROWS = "rows_le_8"


def norm_phrase(text):
    """The priced stub normalization: lowercase, digits masked."""
    lowered = _DIGITS_RE.sub("#", (text or "").lower())
    return RE_WHITESPACE.sub(" ", _NON_PHRASE_RE.sub(" ", lowered)).strip()


def _cell_value(cell):
    """The priced cell grammar: (is_numeric, value) for one cell."""
    c = cell.strip()
    if c in _ZERO_TOKENS:
        return False, 0.0
    core = SCHEMA_PERCENT_RE.sub("", c).strip()
    if not _NUM_RE.match(core):
        return False, 0.0
    neg = core.startswith("(") and core.endswith(")")
    num = core.strip("()$").replace(",", "")
    try:
        val = float(num)
    except ValueError:
        return False, 0.0
    return True, (-val if neg else val)


class TaxReconciliationSeparatorText:
    """One table's grid as the separator reads it: rows of cells."""

    def __init__(self, table_text: str = ""):
        self.table_text = table_text or ""
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
    def from_rows(cls, rows) -> "TaxReconciliationSeparatorText":
        """Grid text from raw context rows (production surface)."""
        table_text = "\n".join(" | ".join(str(c) for c in row) for row in rows)
        return cls(table_text)

    @classmethod
    def from_packet(cls, packet) -> "TaxReconciliationSeparatorText":
        """Grid text from a census packet (priced population)."""
        return cls(packet.get("table_text") or "")


@dataclass(frozen=True)
class TaxReconciliationSeparatorVerdict:
    """The separator verdict for one table: fired legs, if any."""

    fired: bool
    evaluable: bool
    legs: tuple[str, ...]
    detail: str


def movement_nonzero(text: TaxReconciliationSeparatorText) -> int:
    """Nonzero numeric cells on movement lines (priced grammar)."""
    count = 0
    for cells in text.rows:
        joined = " ".join(cells).lower()
        if not any(word in joined for word in MOVE_WORDS):
            continue
        for cell in cells:
            is_num, val = _cell_value(cell)
            if is_num and val != 0:
                count += 1
    return count


def rate_core_present(text: TaxReconciliationSeparatorText) -> bool:
    """The determined rate core: a statutory/effective anchor stub
    naming a rate or tax, plus at least one percentage-bearing row."""
    anchor = any(
        ("statutory" in ph or "effective" in ph) and ("rate" in ph or "tax" in ph)
        for ph in text.stub_phrases
    )
    rate_rows = sum(1 for cells in text.rows if "%" in " ".join(cells))
    return bool(anchor and rate_rows >= 1)


def evaluate_tax_reconciliation_separator(
    text: TaxReconciliationSeparatorText, spec: TaxReconciliationSeparatorSpec
) -> TaxReconciliationSeparatorVerdict:
    """Evaluate one grid against the family's priced conjunction."""
    if not text.rows:
        return TaxReconciliationSeparatorVerdict(
            False, False, (), "separator unevaluable: no grid rows"
        )
    legs: list[str] = []
    if not rate_core_present(text):
        legs.append(LEG_CORE_ABSENT)
    if movement_nonzero(text) <= 0:
        legs.append(LEG_MOVE_NONZERO)
    if len(text.rows) <= spec.max_rows:
        legs.append(LEG_ROWS)
    if len(legs) == 3:
        detail = "separator fired: " + ", ".join(legs)
        return TaxReconciliationSeparatorVerdict(True, True, tuple(legs), detail)
    return TaxReconciliationSeparatorVerdict(False, True, (), "separator clear")


# ---------------- production wiring (stage adapter) ----------------


def evaluate_form_test_tax_reconciliation_separator(table, spec):
    """Stage adapter: evaluate the declared separator over a table."""
    gate_spec = TAX_RECONCILIATION_SEPARATOR_SPECS.get(spec.family)
    if gate_spec is None:
        return TaxReconciliationSeparatorVerdict(
            False, False, (), "no separator spec for family"
        )
    text = TaxReconciliationSeparatorText.from_rows(table.context.rows)
    return evaluate_tax_reconciliation_separator(text, gate_spec)
