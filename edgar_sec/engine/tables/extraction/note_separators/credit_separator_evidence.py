"""Credit separator evidence (TEST_CREDIT_SEPARATOR).
Evaluates the priced claim-local legs over one table: a
credit claim is refused when any leg fires.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.evidence.core_form_evidence import (
    failing_core_form_outcome as fired_separator_outcome,
)
from edgar_sec.engine.tables.extraction.specs.credit_losses_specs import (
    CREDIT_LOSSES_EVIDENCE_SPECS,
)
from edgar_sec.engine.tables.extraction.note_separators.credit_separator_specs import (
    CREDIT_SEPARATOR_SPECS,
    CreditSeparatorSpec,
)
from edgar_sec.foundation.text.patterns import RE_WHITESPACE

__all__ = [
    "CreditSeparatorText",
    "CreditSeparatorVerdict",
    "evaluate_credit_separator",
    "evaluate_form_test_credit_separator",
    "fired_separator_outcome",
]


def _norm(cell) -> str:
    return RE_WHITESPACE.sub(" ", str(cell).strip().lower())


def _row_cells(line: str) -> list[str]:
    return [c for c in (_norm(c) for c in line.split("|")) if c]


class CreditSeparatorText:
    """One table's separator surface: the seat's drawn text
    (caption stack over the grid) plus normalized row stubs."""

    def __init__(self, caption_stack=(), table_text: str = ""):
        self.caption_stack = tuple(caption_stack)
        self.table_text = table_text or ""
        caption = " ".join(self.caption_stack)
        self.drawn = (caption + " \n " + self.table_text).lower()
        lines = self.table_text.split("\n")
        self.has_rows = any(ln.strip() for ln in lines)
        self.stubs = tuple(
            cells[0] for cells in (_row_cells(ln) for ln in lines) if cells
        )

    @classmethod
    def from_rows(cls, rows, caption_stack=()) -> "CreditSeparatorText":
        """Separator text from raw context rows (production)."""
        table_text = "\n".join("|".join(str(c) for c in row) for row in rows)
        return cls(caption_stack, table_text)

    @classmethod
    def from_packet(cls, packet) -> "CreditSeparatorText":
        """Separator text from a census packet (priced frame)."""
        return cls(packet.get("caption_stack") or (), packet.get("table_text") or "")


@dataclass(frozen=True)
class CreditSeparatorVerdict:
    """The separator verdict for one table: fired legs, if any."""

    fired: bool
    evaluable: bool
    legs: tuple[str, ...]
    detail: str


def evaluate_credit_separator(
    text: CreditSeparatorText, spec: CreditSeparatorSpec
) -> CreditSeparatorVerdict:
    """Evaluate one table against the family's priced legs."""
    if not text.has_rows:
        return CreditSeparatorVerdict(
            False, False, (), "separator unevaluable: no grid rows"
        )
    seat_spec = CREDIT_LOSSES_EVIDENCE_SPECS[spec.family]
    present = {
        key
        for key, terms in seat_spec.movement_elements
        if any(term in text.drawn for term in terms)
    }
    fired: list[str] = []
    for leg in spec.legs:
        if leg.scope != "claim-local":
            continue
        if leg.kind == "movement_count":
            count = len(present - {spec.excluded_count_kind})
            if count < spec.min_movement_kinds:
                fired.append(leg.leg_id)
        elif leg.kind == "loan_movement":
            loan_move = any(
                any(term in stub for term in spec.loan_terms) for stub in text.stubs
            )
            bookend = any(
                spec.bookend_term in stub
                and any(q in stub for q in spec.bookend_qualifiers)
                for stub in text.stubs
            )
            if loan_move and not bookend:
                fired.append(leg.leg_id)
    if fired:
        detail = "separator fired: " + ", ".join(fired)
        return CreditSeparatorVerdict(True, True, tuple(fired), detail)
    return CreditSeparatorVerdict(False, True, (), "separator clear")


# ---------------- production wiring (stage adapter) ----------------


def evaluate_form_test_credit_separator(table, spec):
    """Stage adapter: evaluate the declared separator over a table."""
    gate_spec = CREDIT_SEPARATOR_SPECS.get(spec.family)
    if gate_spec is None:
        return CreditSeparatorVerdict(False, False, (), "no separator spec for family")
    context = table.context
    text = CreditSeparatorText.from_rows(context.rows, context.caption_stack)
    return evaluate_credit_separator(text, gate_spec)
