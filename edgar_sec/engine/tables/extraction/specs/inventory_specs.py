"""Inventory seat parameters: the priced rule as data.
The Ruling 18 pass's vocabularies, declared once here for
the inventory_evidence evaluator.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core.profiles import PROV_R18_SEAT_PRICING


@dataclass(frozen=True, slots=True)
class InventoryEvidenceSpec:
    """Inventory seat parameters, declared as data.
    The priced rule's vocabularies: the component-class terms
    counted per stub row, the total-line terms, the recall term."""

    family: str
    test_id: str
    class_terms: tuple[str, ...]
    total_terms: tuple[str, ...]
    finished_term: str
    min_class_rows: int = 2
    provenance: str = PROV_R18_SEAT_PRICING


# Inventory seat specs, keyed by family: the one literal home
# of the kind's parameters, priced by the Ruling 18 pass over
# the Step 1 fresh population (19 TP / 0 FP / 2 FN).
INVENTORY_EVIDENCE_SPECS: dict[str, InventoryEvidenceSpec] = {
    "inventory": InventoryEvidenceSpec(
        family="inventory",
        test_id="inventory_evidence",
        class_terms=(
            "finished goods",
            "work in process",
            "work-in-process",
            "work in progress",
            "raw material",
            "supplies",
            "merchandise",
            "inventory",
            "inventories",
        ),
        total_terms=("total inventories", "total inventory"),
        finished_term="finished",
    ),
}

# The same parameters keyed by test_id, derived at registry load
# for the stage adapter; never a second literal copy.
INVENTORY_EVIDENCE_SPECS_BY_TEST_ID: dict[str, InventoryEvidenceSpec] = {
    spec.test_id: spec for spec in INVENTORY_EVIDENCE_SPECS.values()
}
