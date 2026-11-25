"""Tax seat specs, keyed by family."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    PROV_RULING18_PRICING,
)


@dataclass(frozen=True, slots=True)
class TaxEvidenceSpec:
    """Tax seat parameters, declared as data: the priced
    conjunction's stub anchor and lead context terms, plus
    the hard-veto terms the seat outranks at its claim act."""

    family: str
    test_id: str
    stub_anchor_terms: tuple[str, ...]
    lead_context_terms: tuple[str, ...]
    seat_veto_precedence_terms: tuple[str, ...] = ()
    seat_veto_precedence_floor_terms: tuple[str, ...] = ()
    provenance: str = PROV_RULING18_PRICING


# Tax seat specs, keyed by family: the priced conjunction
# (Ruling 18 pass, seater P 1.000 / R .929 on fresh strata).
TAX_EVIDENCE_SPECS: dict[str, TaxEvidenceSpec] = {
    "tax_reconciliation": TaxEvidenceSpec(
        family="tax_reconciliation",
        test_id="tax_reconciliation_statutory_anchor_seat",
        stub_anchor_terms=("statutory", "computed expected", "expected federal"),
        lead_context_terms=("tax",),
        seat_veto_precedence_terms=(
            "ended march",
            "total",
            "months ended",
            "form 10-k",
        ),
        seat_veto_precedence_floor_terms=("total", "months ended"),
    ),
}


# The same parameters keyed by test_id, derived at registry load
# for the stage adapter; never a second literal copy.
TAX_EVIDENCE_SPECS_BY_TEST_ID: dict[str, TaxEvidenceSpec] = {
    spec.test_id: spec for spec in TAX_EVIDENCE_SPECS.values()
}
