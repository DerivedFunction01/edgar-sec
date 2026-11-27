"""Tax-reconciliation seat evidence: the statutory-anchor seat.

The priced conjunction (Ruling 18 pass): a statutory anchor in
the stub labels and tax context in the lead prose seat the
family; neither leg alone admits.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from edgar_sec.engine.tables.extraction.core.term_index import TermEntry, TermIndex
from edgar_sec.engine.tables.extraction.form_specs.form_test_types import FormTestSpec
from edgar_sec.engine.tables.extraction.core.text.normalize import normalize_text
from edgar_sec.engine.tables.extraction.specs.families.tax_evidence_specs import (
    TAX_EVIDENCE_SPECS_BY_TEST_ID,
    TaxEvidenceSpec,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import TypedTable
from edgar_sec.foundation.text.patterns import RE_NON_ALNUM


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


# Anchor matching folds punctuation runs to single spaces, so a
# quoted or parenthesized caption ('computed "expected" income
# tax') matches its plain anchor term.
def _folded(text: str) -> str:
    return RE_NON_ALNUM.sub(" ", text).strip()


@lru_cache(maxsize=None)
def _spec_index(spec: TaxEvidenceSpec) -> TermIndex:
    """One index over the seat spec's terms: the anchor terms
    in their folded form (reported as the original term) and
    the lead-context terms. Every entry phrase-kind."""
    entries = [
        TermEntry(_folded(term), "anchor", value=term)
        for term in spec.stub_anchor_terms
    ]
    entries += [
        TermEntry(term, "context", value=term) for term in spec.lead_context_terms
    ]
    return TermIndex(entries)


def evaluate_tax_evidence(text: TaxText, spec: TaxEvidenceSpec) -> TaxEvidence:
    """Admit only when both legs of the conjunction are present."""
    index = _spec_index(spec)
    stub_hits = index.scan(_folded(text.stub_text)).get("anchor", frozenset())
    anchor = next(
        (term for term in spec.stub_anchor_terms if term in stub_hits),
        None,
    )
    if anchor is None:
        return TaxEvidence(False, "statutory anchor absent from stub")
    lead_hits = index.scan(text.lead_text).get("context", frozenset())
    context = next(
        (term for term in spec.lead_context_terms if term in lead_hits),
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
