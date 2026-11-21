"""Stock comp seat parameters: the priced rule as data.
Depth-2's vocabularies and thresholds, declared once here
for the stock_comp_evidence evaluator.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core.profiles import PROV_R18_SEAT_PRICING


@dataclass(frozen=True, slots=True)
class StockCompEvidenceSpec:
    """Stock comp seat parameters, declared as data.
    The priced rule's vocabularies: the activity terms counted
    per stub row, the seat terms, the claim form selector."""

    family: str
    test_id: str
    activity_terms: tuple[str, ...]
    granted_term: str
    lead_options_term: str
    units_term: str
    waep_term: str
    outstanding_term: str
    exercisable_term: str
    min_activity_rows: int = 2
    min_range_rows: int = 2
    claim_form: str = "derived"
    provenance: str = PROV_R18_SEAT_PRICING


# Stock comp seat specs, keyed by family: the one literal home
# of the kind's parameters, priced by depth-2 over the Ruling 18
# fresh population (seat 34 TP / 3 FP / 3 FN; derived 35/3/2).
STOCK_COMP_EVIDENCE_SPECS: dict[str, StockCompEvidenceSpec] = {
    "stock_comp_rollforward": StockCompEvidenceSpec(
        family="stock_comp_rollforward",
        test_id="stock_comp_evidence",
        activity_terms=(
            "granted",
            "issued",
            "exercised",
            "forfeited",
            "expired",
            "vested",
            "cancelled",
            "canceled",
            "repurchased",
        ),
        granted_term="granted",
        lead_options_term="stock options",
        units_term="units",
        waep_term="exercise price",
        outstanding_term="outstanding",
        exercisable_term="exercisable",
    ),
}

# The same parameters keyed by test_id, derived at registry load
# for the stage adapter; never a second literal copy.
STOCK_COMP_EVIDENCE_SPECS_BY_TEST_ID: dict[str, StockCompEvidenceSpec] = {
    spec.test_id: spec for spec in STOCK_COMP_EVIDENCE_SPECS.values()
}
