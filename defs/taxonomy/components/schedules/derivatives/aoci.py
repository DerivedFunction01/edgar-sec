"""Accumulated Other Comprehensive Income (AOCI) rollforward and components (ASC 220)."""

from __future__ import annotations

from defs.taxonomy.tables.specs import build_ngram_tier
from defs.text.bow import LexicalEvidencePack, compile_evidence_pack
from defs.text.compounds import (
    expand_alternations,
    expand_variants,
)

# Primary AOCI rollforward headings and headers
_AOCI_HEADINGS = (
    "accumulated other comprehensive income (loss)",
    "accumulated other comprehensive loss",
    "accumulated other comprehensive income",
    "changes in accumulated other comprehensive income",
    "changes in accumulated other comprehensive loss",
    "changes in accumulated other comprehensive income (loss)",
    "changes in aoci",
    "components of accumulated other comprehensive income",
    "components of accumulated other comprehensive loss",
    "components of accumulated other comprehensive income (loss)",
    "reclassifications out of accumulated other comprehensive income",
    "reclassifications out of aoci",
    "reclassification adjustments out of accumulated other comprehensive income",
)

# AOCI component line items / row labels
_AOCI_COMPONENTS = expand_alternations(
    expand_variants(
        (
            "foreign currency translation adjustment",
            "foreign currency translation gain (loss)",
            "unrealized gain (loss) on cash flow hedge",
            "unrealized gain (loss) on available-for-sale securities",
            "unrealized gain (loss) on available-for-sale debt securities",
            "unrealized holding gain (loss) on available-for-sale securities",
            "unrealized gain (loss) on derivative instrument",
            "pension and other postretirement benefit adjustment",
            "defined benefit pension and postretirement plan adjustment",
            "prior service credit (cost)",
            "net actuarial gain (loss)",
        )
    ),
    (
        "amortization of defined benefit pension items",
        "amounts reclassified from accumulated other comprehensive income",
        "reclassifications to earnings",
        "reclassifications into net income",
        "other comprehensive income (loss), net of tax",
        "other comprehensive income (loss), before tax",
    ),
)

AOCI_PRIMARY_TERMS: tuple[str, ...] = expand_alternations(
    _AOCI_HEADINGS,
    _AOCI_COMPONENTS,
)

AOCI_SECONDARY_TERMS: tuple[str, ...] = (
    "cash flow hedges",
    "foreign currency translation",
    "defined benefit plans",
    "available-for-sale securities",
    "beginning balance",
    "ending balance",
    "other comprehensive income",
    "other comprehensive loss",
    "before reclassifications",
    "amounts reclassified",
    "net current-period other comprehensive income",
)

AOCI_EVIDENCE_PACK: LexicalEvidencePack = compile_evidence_pack(
    LexicalEvidencePack(
        name="aoci",
        tiers=tuple(
            t
            for t in (
                build_ngram_tier(
                    "aoci_primary",
                    AOCI_PRIMARY_TERMS,
                    priority=10,
                    value=2,
                    min_distinct_hits=2,
                ),
                build_ngram_tier(
                    "aoci_support",
                    AOCI_SECONDARY_TERMS,
                    priority=5,
                    value=1,
                    support=True,
                ),
            )
            if t is not None
        ),
        exclusion_terms=("activities",),
    )
)
