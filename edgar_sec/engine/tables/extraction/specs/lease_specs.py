"""Lease seat parameters: the priced rule as data.
The depth-4 attribution cell's vocabularies, declared once
here for the lease_evidence evaluator.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core.profiles import PROV_R18_SEAT_PRICING


@dataclass(frozen=True, slots=True)
class LeaseEvidenceSpec:
    """Lease seat parameters, declared as data.
    The priced rule's vocabularies: the total-line terms,
    the present-value terms, the class trio, ladder bounds."""

    family: str
    test_id: str
    total_terms: tuple[str, ...]
    pv_terms: tuple[str, ...]
    class_terms: tuple[str, ...]
    core_min_year_labels: int = 3
    named_min_year_labels: int = 2
    thereafter_prefix: str = "thereafter"
    provenance: str = PROV_R18_SEAT_PRICING


# Lease seat specs, keyed by family: the one literal home
# of the kind's parameters, priced by the depth-4 run over
# the R18 population (seat 21 TP / 2 FP / 2 FN).
LEASE_EVIDENCE_SPECS: dict[str, LeaseEvidenceSpec] = {
    "lease_maturity": LeaseEvidenceSpec(
        family="lease_maturity",
        test_id="lease_evidence",
        total_terms=(
            "total lease payments",
            "total minimum lease payments",
            "total future minimum",
        ),
        pv_terms=(
            "present value",
            "amounts representing interest",
            "imputed interest",
            "less interest",
        ),
        class_terms=("operating lease", "finance lease", "capital lease"),
    ),
}

# The same parameters keyed by test_id, derived at registry load
# for the stage adapter; never a second literal copy.
LEASE_EVIDENCE_SPECS_BY_TEST_ID: dict[str, LeaseEvidenceSpec] = {
    spec.test_id: spec for spec in LEASE_EVIDENCE_SPECS.values()
}
