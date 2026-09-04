"""Cross-asset / multi-category derivative structures and ASC 815 master schedule disclosures."""

from __future__ import annotations

from defs.taxonomy.components.schedules.derivatives.bases import (
    UNAMBIGUOUS_DERIVATIVE_SUFFIXES,
    UNIVERSAL_UNAMBIGUOUS_BASES,
)
from defs.text.compounds import (
    expand_alternations,
    expand_variants,
)

# Cross-Asset / Multi-Category Structures derived from universal unambiguous bases
CROSS_ASSET_STRUCTURES: tuple[str, ...] = expand_variants(UNIVERSAL_UNAMBIGUOUS_BASES)

# Standalone unambiguous derivative suffixes (e.g. 'derivative asset', 'hedging instrument')
STANDALONE_DERIVATIVE_SUFFIXES: tuple[str, ...] = expand_variants(
    UNAMBIGUOUS_DERIVATIVE_SUFFIXES
)

# Standard heading phrases for dedicated derivative disclosures
DERIVATIVE_HEADING_TERMS: tuple[str, ...] = (
    "derivatives and hedging activities",
    "derivative instruments and hedging activities",
    "accounting for derivative instruments and hedging activities",
    "derivative financial instruments",
    "derivative instruments",
    "fair value of derivative instruments",
    "fair value of derivatives",
    "notional amounts of derivative instruments",
    "notional amount of derivative contracts",
    "hedging instruments and risk management activities",
    "derivative assets and liabilities",
    "derivative contracts",
)

# ASC 815 Hedge Designation Tiers
HEDGE_DESIGNATION_TERMS: tuple[str, ...] = (
    "derivatives designated as hedging instruments",
    "derivatives not designated as hedging instruments",
    "designated as cash flow hedges",
    "designated as fair value hedges",
    "designated as net investment hedges",
    "not designated as hedging instruments",
    "not designated as hedges",
    "undesignated derivative instruments",
    "economic hedges not designated",
    "non-designated derivative instruments",
    "qualifying hedging relationships",
    "qualifying cash flow hedges",
    "qualifying fair value hedges",
    "cash flow hedging relationships",
    "fair value hedging relationships",
)

# Balance sheet location & notional amount disclosure rows/headers
DERIVATIVE_BALANCE_SHEET_NOTIONAL_TERMS: tuple[str, ...] = expand_alternations(
    expand_variants(
        (
            "notional amount",
            "notional value",
            "notional principal amount",
            "total notional amount",
            "derivative asset",
            "derivative liability",
            "gross derivative asset",
            "gross derivative liability",
            "gross positive fair value",
            "gross negative fair value",
            "fair value of derivative contract",
            "fair value of derivative instrument",
            "derivative assets fair value",
            "derivative liabilities fair value",
            "total derivative instruments",
        )
    ),
    (
        "balance sheet location",
        "balance sheet classification",
        "counterparty netting",
        "master netting arrangements",
        "gross amounts recognized",
        "net amounts presented in the balance sheet",
    ),
)

# Income and OCI gain/loss presentation rows/headers (ASC 815-10-50)
DERIVATIVE_GAIN_LOSS_TERMS: tuple[str, ...] = (
    "gain (loss) recognized in oci on derivatives",
    "gain or loss recognized in oci on derivatives",
    "amount of gain (loss) recognized in oci on derivatives",
    "gain (loss) reclassified from aoci into earnings",
    "gain (loss) reclassified from aoci into income",
    "amount of gain (loss) reclassified from aoci into income",
    "amount of gain or loss recognized in income on derivatives",
    "location of gain (loss) recognized in income on derivatives",
    "effect of derivative instruments on consolidated statements of operations",
    "effect of derivative instruments on the statement of operations",
    "effect of derivative instruments on the consolidated statements of income",
)

ASC_815_MASTER_DISCLOSURES: tuple[str, ...] = expand_alternations(
    DERIVATIVE_HEADING_TERMS,
    HEDGE_DESIGNATION_TERMS,
    DERIVATIVE_BALANCE_SHEET_NOTIONAL_TERMS,
    DERIVATIVE_GAIN_LOSS_TERMS,
)

GENERIC_DERIVATIVE_TERMS: tuple[str, ...] = expand_alternations(
    CROSS_ASSET_STRUCTURES,
    STANDALONE_DERIVATIVE_SUFFIXES,
    ASC_815_MASTER_DISCLOSURES,
)

# Cross-Asset & Non-Financial Noise Guards owned by Generic module
GENERIC_NON_FINANCIAL_PHRASES: tuple[str, ...] = expand_variants(
    (
        # IP & Software
        "derivative work",
        "open source",
        "general public license",
        "creative commons",
        # Bio / Chemical
        "cellulose derivative",
        "chemical derivative",
        "polymer derivative",
        "derivative product",
        "derivative compound",
        "plasma derivative",
        "blood derivative",
        # Corporate restructuring swaps
        "debt-for-equity swap",
        "land swap",
        "property swap",
        "asset swap",
        "real estate swap",
        "spectrum swap",
        # Physical non-financial instruments
        "surgical instrument",
        "medical instrument",
        "dental instrument",
        "measuring instrument",
        "optical instrument",
    )
)

GENERIC_UNIGRAM_VETOES: tuple[str, ...] = (
    "cellulose",
    "plasma",
    "fractionation",
    "cannabinoid",
    "cannabinoids",
    "cannabis",
    "morphine",
    "opioid",
    "opioids",
    "biosimilar",
    "biosimilars",
    "enzymes",
    "proteins",
    "surgical",
    "dental",
    "acoustic",
    "microscope",
    "integrals",
    "calculus",
    "gradients",
    "gpl",
)
