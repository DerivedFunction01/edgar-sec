"""Pension core-anchor gate: disjunctive ASC 715 subform anchors.

The gate parameters are declared as data in this module's
PENSION_ANCHOR_SPECS; a claim requires one anchor.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.normalize import normalize_text
from edgar_sec.engine.tables.extraction.profiles import PROV_PENSION_ANCHOR
from edgar_sec.foundation.text.dates import YEAR_TOKEN_SEARCH_RE


@dataclass(frozen=True, slots=True)
class PensionAnchorSpec:
    """Pension core-anchor gate parameters, declared as data.
    The core is disjunctive: any one subform anchor satisfies it;
    the oci leg completes subform (vii), amounts in OCI."""

    family: str
    npbc_groups: tuple[tuple[str, ...], ...]
    npbc_min_groups: int
    walk_subject_terms: tuple[str, ...]
    walk_open_terms: tuple[str, ...]
    walk_close_terms: tuple[str, ...]
    assumptions_anchor_term: str
    assumptions_partner_terms: tuple[str, ...]
    payments_min_year_stubs: int
    payments_context_terms: tuple[str, ...]
    sensitivity_anchor_term: str
    sensitivity_subject_terms: tuple[str, ...]
    funded_terms: tuple[str, ...]
    allocation_asset_terms: tuple[str, ...]
    allocation_context_terms: tuple[str, ...]
    oci_phrases: tuple[str, ...]
    oci_component_terms: tuple[str, ...]
    provenance: str = PROV_PENSION_ANCHOR


# Pension core-anchor gate specs, keyed by family: the one literal
# home of the gate kind's parameters, priced over the adjudicated
# literal population (45 trues, 9 confirmed falses, 3 mimics).
PENSION_ANCHOR_SPECS: dict[str, PensionAnchorSpec] = {
    "pension": PensionAnchorSpec(
        family="pension",
        npbc_groups=(
            ("service cost",),
            ("interest cost",),
            ("expected return",),
            (
                "amortization",
                "prior service",
                "recognized actuarial",
                "recognized net",
                "net amortization",
            ),
        ),
        npbc_min_groups=3,
        walk_subject_terms=("benefit obligation", "plan assets"),
        walk_open_terms=("beginning",),
        walk_close_terms=("end of", "ending"),
        assumptions_anchor_term="discount rate",
        assumptions_partner_terms=("expected", "compensation", "trend rate"),
        payments_min_year_stubs=4,
        payments_context_terms=("benefit", "pension"),
        sensitivity_anchor_term="percentage point",
        sensitivity_subject_terms=("benefit obligation", "service"),
        funded_terms=(
            "accumulated benefit obligation",
            "projected benefit obligation",
            "funded status",
            "underfunded",
        ),
        allocation_asset_terms=(
            "equity securities",
            "fixed income",
            "debt securities",
        ),
        allocation_context_terms=("plan asset", "retirement", "pension"),
        oci_phrases=(
            "other comprehensive income",
            "other comprehensive loss",
        ),
        oci_component_terms=("actuarial", "prior service", "unrecognized"),
    ),
}


@dataclass(frozen=True, slots=True)
class PensionText:
    """One geometry's gate text: stubs, grid, lead, following prose."""

    stubs: tuple[str, ...] = ()
    grid_text: str = ""
    lead: str = ""
    prose_after: str = ""

    @property
    def stubtext(self) -> str:
        """The stub labels as one newline-joined text."""
        return "\n".join(self.stubs)

    @classmethod
    def from_geometry(cls, geometry) -> PensionText:
        """Gate text from a competition GeometryText (duck-typed)."""
        return cls(
            stubs=tuple(normalize_text(stub) for stub in geometry.stubs),
            grid_text=normalize_text(geometry.grid_text),
            lead=normalize_text(geometry.lead),
            prose_after=normalize_text(getattr(geometry, "prose_after", "") or ""),
        )


@dataclass(frozen=True, slots=True)
class PensionAnchors:
    """The gate verdict for one geometry: its core anchor set."""

    anchors: frozenset[str]
    admitted: bool
    detail: str


def pension_anchor_set(text: PensionText, spec: PensionAnchorSpec) -> frozenset[str]:
    """The core anchors firing on the prose-completed surfaces.
    Surfaces are normalized at this leg, so a directly constructed
    text reads exactly as from_geometry's does."""
    stubs = tuple(normalize_text(stub) for stub in text.stubs)
    plain_stubtext = "\n".join(stubs)
    after = normalize_text(text.prose_after)
    stubtext = plain_stubtext + "\n" + after
    low = normalize_text(text.grid_text) + "\n" + after
    lead = normalize_text(text.lead) + " " + after
    anchors: set[str] = set()
    # The oci leg reads the stub surface alone, as priced: its
    # conjunction was priced over production stubtext, not completed.
    if any(x in plain_stubtext for x in spec.oci_phrases) and any(
        x in plain_stubtext for x in spec.oci_component_terms
    ):
        anchors.add("oci")
    groups = sum(1 for grp in spec.npbc_groups if any(x in stubtext for x in grp))
    if groups >= spec.npbc_min_groups:
        anchors.add("npbc")
    if (
        any(x in low for x in spec.walk_subject_terms)
        and any(x in low for x in spec.walk_open_terms)
        and any(x in low for x in spec.walk_close_terms)
    ):
        anchors.add("walk")
    if spec.assumptions_anchor_term in stubtext and any(
        x in stubtext for x in spec.assumptions_partner_terms
    ):
        anchors.add("assumptions")
    years = sum(1 for s in stubs if YEAR_TOKEN_SEARCH_RE.search(s))
    if years >= spec.payments_min_year_stubs and any(
        x in lead for x in spec.payments_context_terms
    ):
        anchors.add("payments")
    if spec.sensitivity_anchor_term in low and any(
        x in low for x in spec.sensitivity_subject_terms
    ):
        anchors.add("sensitivity")
    if any(x in stubtext for x in spec.funded_terms):
        anchors.add("funded")
    if any(x in stubtext for x in spec.allocation_asset_terms) and any(
        x in lead for x in spec.allocation_context_terms
    ):
        anchors.add("allocation")
    return frozenset(anchors)


def evaluate_pension_anchor(
    text: PensionText, spec: PensionAnchorSpec
) -> PensionAnchors:
    """Evaluate one geometry's text against the family's gate spec."""
    anchors = pension_anchor_set(text, spec)
    if anchors:
        detail = "core anchor: " + ", ".join(sorted(anchors))
        return PensionAnchors(anchors, True, detail)
    return PensionAnchors(anchors, False, "no core anchor")
