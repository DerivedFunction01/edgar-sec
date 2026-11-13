"""Signature profile types and shared competition constants.

The measured terms live in the signature_terms_* data modules
beside this one (Step 1 measurement over the Step 11C adjudicated
corpora); weights are smoothed log odds ratios of member vs
foreign-member channel presence.
"""

from __future__ import annotations

from dataclasses import dataclass

PROV_STEP1_MEASUREMENT = "improvement-step1:measurement-2026-11-13"
PROV_STEP0_LEXICON = "improvement-step0:brief-lexicon"
PROV_STEP1_MINED = "improvement-step1:mined-ngrams"

CHANNELS = ("caption", "leadin", "notehead", "stub")

# Channel weights priced from Step 0's channel outcomes (correct /
# (correct + wrong), pooled B+D, normalized to lead-in = 1.0).
CHANNEL_WEIGHTS: dict[str, float] = {
    "caption": 1.10,
    "leadin": 1.00,
    "notehead": 0.86,
    "stub": 0.93,
}


@dataclass(frozen=True, slots=True)
class SignatureTerm:
    """One measured profile term in one evidence channel."""

    family: str
    channel: str
    term: str
    weight: float
    member_hits: int
    foreign_hits: int
    provenance: str = PROV_STEP1_MEASUREMENT


@dataclass(frozen=True, slots=True)
class ContainmentEdge:
    """A measured edge: subset vocabulary legitimately inside a parent."""

    subset: str
    parent: str
    discount: float
    support: str
    provenance: str = PROV_STEP1_MEASUREMENT


# Edges measured before Step 1: the registry containment census
# (aoci sections inside equity statements, lift 66x), the verdict's
# combined-presentation split groups (CI inside income grids), and
# the registry co-note census (deferred_tax x tax_reconciliation).
CONTAINMENT_EDGES: tuple[ContainmentEdge, ...] = (
    ContainmentEdge(
        "aoci_rollforward", "equity_statement", 0.75, "census lift 66x, 4 of 9 parents"
    ),
    ContainmentEdge(
        "equity_statement", "aoci_rollforward", 0.50, "parent headings in rollforwards"
    ),
    ContainmentEdge(
        "comprehensive_income",
        "income_statement",
        0.50,
        "combined-presentation split groups",
    ),
    ContainmentEdge(
        "income_statement",
        "comprehensive_income",
        0.50,
        "combined-presentation split groups",
    ),
    ContainmentEdge(
        "deferred_tax", "tax_reconciliation", 0.50, "co-note colocation 0.50 / 0.857"
    ),
    ContainmentEdge(
        "tax_reconciliation", "deferred_tax", 0.50, "co-note colocation 0.50 / 0.857"
    ),
)
