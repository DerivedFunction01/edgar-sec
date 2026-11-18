"""Tax-reconciliation seat evidence: the statutory-anchor seat.

The priced conjunction (Ruling 18 pass): a statutory anchor in
the stub labels and tax context in the lead prose seat the
family; neither leg alone admits.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.form_test_specs import (
    TAX_EVIDENCE_SPECS_BY_TEST_ID,
    FormTestSpec,
    TaxEvidenceSpec,
)
from edgar_sec.engine.tables.extraction.normalize import normalize_text
from edgar_sec.engine.tables.extraction.typed_rows import TypedTable


@dataclass(frozen=True, slots=True)
class TaxText:
    """One table's seat text: the stub labels and the lead prose."""

    stub_text: str = ""
    lead_text: str = ""

    @classmethod
    def from_table(cls, table: TypedTable) -> TaxText:
        """Derive the seat text from the typed table's own surfaces."""
        stubs = " ".join(row.label for row in table.rows if row.label)
        return cls(
            stub_text=normalize_text(stubs),
            lead_text=normalize_text(table.context.prose_before or ""),
        )


@dataclass(frozen=True, slots=True)
class TaxEvidence:
    """Seat verdict for one table: admitted, with the reason."""

    admitted: bool
    detail: str


def evaluate_tax_evidence(text: TaxText, spec: TaxEvidenceSpec) -> TaxEvidence:
    """Admit only when both legs of the conjunction are present."""
    anchor = next(
        (term for term in spec.stub_anchor_terms if term in text.stub_text),
        None,
    )
    if anchor is None:
        return TaxEvidence(False, "statutory anchor absent from stub")
    context = next(
        (term for term in spec.lead_context_terms if term in text.lead_text),
        None,
    )
    if context is None:
        return TaxEvidence(False, "tax context absent from lead")
    detail = f"anchor '{anchor}' in stub; context '{context}' in lead"
    return TaxEvidence(True, detail)


def evaluate_form_test_tax(table: TypedTable, spec: FormTestSpec) -> TaxEvidence:
    """Form-test stage adapter: resolve the seat spec, evaluate."""
    seat_spec = TAX_EVIDENCE_SPECS_BY_TEST_ID.get(spec.test_id)
    if seat_spec is None:
        return TaxEvidence(False, "no tax seat spec for test")
    return evaluate_tax_evidence(TaxText.from_table(table), seat_spec)
