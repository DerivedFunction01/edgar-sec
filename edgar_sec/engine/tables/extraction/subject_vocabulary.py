"""Cascade vocabulary entries for the Step 2 families.

Terms derive from the subject-evidence map's stub channel,
re-priced on the v3 base; composed into calibration's
PATTERNS with the Step 2 pricing provenance.
"""

from __future__ import annotations

# (family, term, channel, member hits, member share, exclusivity)
STEP2_PATTERN_ENTRIES: tuple[tuple[str, str, str, int, float, float], ...] = (
    ("ppe", "accumulated depreciation", "label", 12, 0.75, 0.324),
    ("ppe", "less: accumulated depreciation", "label", 7, 0.438, 0.583),
    ("ppe", "leasehold improvements", "label", 7, 0.438, 0.412),
    ("ppe", "accumulated depreciation and amortization", "label", 5, 0.312, 0.455),
    ("ppe", "furniture and fixtures", "label", 3, 0.188, 0.5),
    ("ppe", "machinery and equipment", "label", 3, 0.188, 0.5),
    (
        "ppe",
        "less: accumulated depreciation and amortization",
        "label",
        3,
        0.188,
        1.0,
    ),
    ("comprehensive_income", "total comprehensive income", "label", 4, 0.25, 0.571),
    (
        "comprehensive_income",
        "foreign currency translation adjustments",
        "label",
        4,
        0.25,
        0.308,
    ),
    (
        "comprehensive_income",
        "other comprehensive income (loss), net of tax",
        "label",
        3,
        0.188,
        0.375,
    ),
    (
        "comprehensive_income",
        "total other comprehensive income (loss)",
        "label",
        3,
        0.188,
        0.375,
    ),
    ("derivatives_hedging", "forward contracts", "label", 6, 0.171, 0.6),
    ("derivatives_hedging", "interest rate swaps", "label", 4, 0.114, 0.4),
    ("derivatives_hedging", "commodity contracts", "label", 3, 0.086, 0.6),
    (
        "derivatives_hedging",
        "derivatives designated as hedging instruments",
        "label",
        3,
        0.086,
        1.0,
    ),
    (
        "derivatives_hedging",
        "derivatives not designated as hedging instruments",
        "label",
        2,
        0.057,
        1.0,
    ),
    ("derivatives_hedging", "notional amount", "label", 2, 0.057, 0.4),
    ("derivatives_hedging", "swaps", "token", 9, 0.257, 0.6),
    ("derivatives_hedging", "hedging", "token", 7, 0.2, 0.412),
    ("debt_maturity", "thereafter", "label", 9, 0.6, 0.243),
)
