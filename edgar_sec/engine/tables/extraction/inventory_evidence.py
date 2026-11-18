"""Inventory evidence seat: the ASC 330 composition seat.
A claim seats on the component-class core or on the
finished-goods stub vocabulary (the Ruling 18 priced form).
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.form_test_specs import FormTestSpec
from edgar_sec.engine.tables.extraction.inventory_specs import (
    INVENTORY_EVIDENCE_SPECS_BY_TEST_ID,
    InventoryEvidenceSpec,
)
from edgar_sec.engine.tables.extraction.typed_rows import TypedTable


@dataclass(frozen=True, slots=True)
class InventoryText:
    """One geometry's seat text: the grid's stub labels."""

    stubs: tuple[str, ...] = ()

    @property
    def stub_text(self) -> str:
        """Every stub label as one text: the priced surface."""
        return " ".join(self.stubs)

    @classmethod
    def from_table(cls, table: TypedTable) -> InventoryText:
        """Seat text from a typed table: first cells, lowered."""
        return cls(
            stubs=tuple(
                (row[0] if row else "").strip().lower() for row in table.context.rows
            )
        )


@dataclass(frozen=True, slots=True)
class InventoryLegs:
    """The priced rule's leg readings over one geometry's stubs."""

    class_rows: int
    classes2: bool
    total_line: bool
    core: bool
    finished: bool

    @property
    def claim(self) -> bool:
        """The seat claim: the core, or the finished-goods leg."""
        return self.core or self.finished


def legs_for(text: InventoryText, spec: InventoryEvidenceSpec) -> InventoryLegs:
    """Every leg of the priced rule over one geometry's stubs."""
    class_rows = sum(
        1 for stub in text.stubs if any(term in stub for term in spec.class_terms)
    )
    classes2 = class_rows >= spec.min_class_rows
    total_line = any(term in text.stub_text for term in spec.total_terms)
    return InventoryLegs(
        class_rows=class_rows,
        classes2=classes2,
        total_line=total_line,
        core=classes2 and total_line,
        finished=spec.finished_term in text.stub_text,
    )


@dataclass(frozen=True, slots=True)
class InventoryEvidence:
    """The seat verdict for one geometry under the seat's spec."""

    admitted: bool
    evaluable: bool
    legs: InventoryLegs | None
    detail: str


def evaluate_inventory(
    text: InventoryText, spec: InventoryEvidenceSpec
) -> InventoryEvidence:
    """The seat verdict over one geometry's seat text."""
    legs = legs_for(text, spec)
    if legs.core:
        return InventoryEvidence(True, True, legs, "core: component classes to total")
    if legs.finished:
        return InventoryEvidence(True, True, legs, "finished-goods stub vocabulary")
    return InventoryEvidence(
        False, True, legs, f"no seat leg (class rows {legs.class_rows})"
    )


def evaluate_form_test_inventory(
    table: TypedTable, spec: FormTestSpec
) -> InventoryEvidence:
    """Stage adapter: evaluate the declared seat spec over a table."""
    gate_spec = INVENTORY_EVIDENCE_SPECS_BY_TEST_ID.get(spec.test_id)
    if gate_spec is None:
        return InventoryEvidence(False, False, None, "no seat spec for test")
    if not table.context.rows:
        return InventoryEvidence(False, False, None, "no grid rows")
    return evaluate_inventory(InventoryText.from_table(table), gate_spec)
