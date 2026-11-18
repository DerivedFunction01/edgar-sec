"""AOCI claim-shape spec: the subject leg's terms."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AociClaimShapeSpec:
    """AOCI claim shape (Step 9 pricing): the subject leg's terms.
    A standalone aoci_rollforward claim requires the family's core
    shape: a beginning-to-ending walk plus an AOCI subject."""

    component_terms: tuple[str, ...]
    min_components: int = 2
    subject_phrase: str = "other comprehensive"
    lead_phrase: str = "accumulated other comprehensive"
    provenance: str = "step9:aoci-claim-shape-pricing"


AOCI_CLAIM_SHAPE_SPEC = AociClaimShapeSpec(
    component_terms=(
        "foreign currency",
        "cash flow hedge",
        "derivative",
        "defined benefit",
        "pension",
        "postretirement",
        "available-for-sale",
        "available for sale",
        "debt securities",
        "securities",
        "unrealized",
        "translation",
        "hedg",
    ),
)
