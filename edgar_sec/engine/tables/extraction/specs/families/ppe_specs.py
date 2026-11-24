"""PPE seat parameters: the priced rule as data.
The re-derived vocabulary's term sets, declared once here
for the ppe_evidence evaluator.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    PROV_R18_SEAT_PRICING,
)


@dataclass(frozen=True, slots=True)
class PpeEvidenceSpec:
    """PPE seat parameters, declared as data.
    The priced rule's vocabularies: the class terms, the
    net-close literals, the guard terms, the geometry terms."""

    family: str
    test_id: str
    class_terms: tuple[str, ...]
    contra_term: str = "accumulated depreciation"
    net_close_literals: tuple[str, ...] = (
        "property and equipment, net",
        "property, plant and equipment, net",
    )
    bs_guard_term: str = "total assets"
    lease_guard_terms: tuple[str, ...] = (
        "lease liabilities",
        "operating lease equipment",
    )
    net_col_terms: tuple[str, ...] = ("net book value", "net real estate")
    col1_header_terms: tuple[str, ...] = (
        "gross carrying amount",
        "accumulated depreciation",
        "net book value",
    )
    s3_marker_term: str = "encumbrances"
    s3_cost_terms: tuple[str, ...] = ("initial cost", "gross amount")
    roll_stub_terms: tuple[str, ...] = ("real estate", "gross")
    rights_term: str = "rights"
    depletion_term: str = "depletion"
    comp_lead_term: str = "property and equipment"
    bookend_begin_terms: tuple[str, ...] = ("beginning",)
    bookend_end_terms: tuple[str, ...] = (
        "ending",
        "end of year",
        "end of period",
    )
    bookend_forward_begin_terms: tuple[str, ...] = (
        "brought forward",
        "balance forward",
    )
    bookend_forward_end_terms: tuple[str, ...] = (
        "carried forward",
        "carryforward",
    )
    provenance: str = PROV_R18_SEAT_PRICING


# PPE seat specs, keyed by family: the one literal home of
# the kind's parameters, priced by the depth lane's Phase 2
# run over the R18 population (seat 25 TP / 2 FP / 0 FN).
PPE_EVIDENCE_SPECS: dict[str, PpeEvidenceSpec] = {
    "ppe": PpeEvidenceSpec(
        family="ppe",
        test_id="ppe_evidence",
        class_terms=(
            "land",
            "building",
            "machinery",
            "equipment",
            "furniture",
            "fixture",
            "vehicle",
            "leasehold",
            "construction in progress",
            "computer",
            "software",
            "improvements",
        ),
    ),
}

# The same parameters keyed by test_id, derived at registry load
# for the stage adapter; never a second literal copy.
PPE_EVIDENCE_SPECS_BY_TEST_ID: dict[str, PpeEvidenceSpec] = {
    spec.test_id: spec for spec in PPE_EVIDENCE_SPECS.values()
}
