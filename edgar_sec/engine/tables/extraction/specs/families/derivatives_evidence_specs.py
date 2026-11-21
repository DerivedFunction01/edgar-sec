"""Derivatives-evidence gate specs, keyed by family."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.commodity_terms import (
    COMMODITY_HEADER_PHRASE,
    COMMERCIAL_TERMS,
    NPNS_PHRASES,
)
from edgar_sec.engine.tables.extraction.core.subjects.profiles import (
    PROV_DERIVATIVES_EVIDENCE,
)


@dataclass(frozen=True, slots=True)
class DerivativesEvidenceSpec:
    """Derivatives-evidence gate parameters, declared as data.
    An unambiguous base decides alone, ambiguous bases decide only
    in accumulation; the equity / NPNS lists carve subjects out."""

    family: str
    test_id: str
    unambiguous_bases: tuple[str, ...]
    ambiguous_bases: tuple[str, ...]
    stem_bases: tuple[tuple[str, str], ...]
    designation_phrases: tuple[str, ...]
    anchor_terms: tuple[str, ...]
    suffix_terms: tuple[str, ...]
    commercial_terms: tuple[str, ...]
    npns_phrases: tuple[str, ...]
    equity_comp_terms: tuple[str, ...]
    equity_prefixes: tuple[str, ...]
    aoci_subject_phrases: tuple[str, ...]
    commodity_header: str
    effects_phrases: tuple[str, ...]
    effects_leadin_phrases: tuple[str, ...]
    offsetting_phrases: tuple[str, ...]
    min_period_rows: int = 2
    provenance: str = PROV_DERIVATIVES_EVIDENCE


# Derivatives-evidence gate specs, keyed by family: the one
# literal home of the gate kind's parameters, priced against
# the measured evidence-class split over the 58 specimens.
DERIVATIVES_EVIDENCE_SPECS: dict[str, DerivativesEvidenceSpec] = {
    "derivatives_hedging": DerivativesEvidenceSpec(
        family="derivatives_hedging",
        test_id="derivatives_hedging_evidence_gate",
        unambiguous_bases=(
            "swap",
            "swaps",
            "forward",
            "forwards",
            "collar",
            "collars",
            "derivative",
            "derivatives",
            "futures",
            "swaption",
            "swaptions",
            "straddle",
            "strangle",
        ),
        ambiguous_bases=(
            "option",
            "options",
            "cap",
            "caps",
            "floor",
            "floors",
            "put",
            "puts",
            "call",
            "calls",
            "hedge",
            "hedges",
            "hedging",
            "lock",
            "locks",
        ),
        stem_bases=(("capped", "cap"),),
        designation_phrases=(
            "designated as hedging",
            "not designated",
            "designated hedging",
            "hedging instruments",
            "derivative assets",
            "derivative liabilities",
            "derivative contracts",
            "derivative instruments",
            "derivative financial instruments",
            "cash flow hedge",
            "fair value hedge",
            "net investment hedge",
            "hedge accounting",
            "derivatives designated",
        ),
        anchor_terms=(
            "notional",
            "fair value",
            "fair market value",
            "balance sheet location",
            "income statement location",
            "offsetting",
            "netting",
            "gross amounts",
            "exercise price",
        ),
        suffix_terms=("contract", "contracts", "instrument", "instruments"),
        commercial_terms=COMMERCIAL_TERMS,
        npns_phrases=NPNS_PHRASES,
        equity_comp_terms=(
            "restricted stock",
            "stock appreciation",
            "employee stock",
            "equity incentive",
            "options granted",
            "shares available for future",
            "weighted-average exercise",
            "weighted average exercise",
        ),
        equity_prefixes=("stock", "equity", "share", "dividend"),
        aoci_subject_phrases=(
            "accumulated other comprehensive income components",
            "details about accumulated other comprehensive",
        ),
        commodity_header=COMMODITY_HEADER_PHRASE,
        effects_phrases=(
            "effects of cash flow hedges",
            "effect of derivative",
            "effects of derivative",
            "effect of our derivative",
        ),
        effects_leadin_phrases=(
            "effects of cash flow hedges",
            "effect of our derivative",
        ),
        offsetting_phrases=(
            "offsetting",
            "amounts offset",
            "not offset",
            "gross amounts offset",
        ),
    ),
}


# The same parameters keyed by test_id, derived at registry load
# for the stage adapter; never a second literal copy.
DERIVATIVES_EVIDENCE_SPECS_BY_TEST_ID: dict[str, DerivativesEvidenceSpec] = {
    spec.test_id: spec for spec in DERIVATIVES_EVIDENCE_SPECS.values()
}
