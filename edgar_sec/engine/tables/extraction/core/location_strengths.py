"""Location strengths: measured values with calibration provenance."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.core.registry import LocationSpec

LOCATION_STRENGTHS: tuple[LocationSpec, ...] = (
    LocationSpec(
        "aoci_rollforward", 8, ((None, 4), ("ITEM 16", 2), ("ITEM 1", 2)), 0.875, 0.125
    ),
    LocationSpec(
        "balance_sheet",
        117,
        (("ITEM 1", 34), ("ITEM 8", 29), ("ITEM 16", 17), (None, 13), ("ITEM 15", 11)),
        0.222,
        0.034,
    ),
    LocationSpec(
        "cash_flow",
        151,
        (
            ("ITEM 8", 39),
            ("ITEM 1", 37),
            ("ITEM 7", 20),
            ("ITEM 16", 16),
            ("ITEM 2", 16),
        ),
        0.238,
        0.013,
    ),
    LocationSpec("cover_layout", 1, ((None, 1)), 0.0, 0.0),
    LocationSpec(
        "debt_maturity",
        6,
        (("ITEM 1", 2), ("ITEM 7A", 1), ("ITEM 16", 1), ("ITEM 8", 1), (None, 1)),
        0.833,
        0.167,
    ),
    LocationSpec(
        "deferred_tax",
        44,
        (("ITEM 16", 19), ("ITEM 8", 16), ("ITEM 15", 3), (None, 3), ("ITEM 7A", 1)),
        0.864,
        0.045,
    ),
    LocationSpec("derivatives_hedging", 2, ((None, 1), ("ITEM 16", 1)), 1.0, 0.0),
    LocationSpec(
        "eps_reconciliation",
        24,
        (("ITEM 1", 7), ("ITEM 16", 5), ("ITEM 8", 5), ("ITEM 4", 3), ("ITEM 2", 1)),
        0.917,
        0.042,
    ),
    LocationSpec(
        "equity_statement", 9, (("ITEM 8", 4), ("ITEM 1", 3), ("ITEM 4", 2)), 0.0, 0.0
    ),
    LocationSpec(
        "fair_value",
        18,
        (("ITEM 1", 9), ("ITEM 8", 3), ("ITEM 4", 3), ("ITEM 16", 2), (None, 1)),
        0.889,
        0.056,
    ),
    LocationSpec(
        "income_statement",
        154,
        (
            ("ITEM 8", 34),
            ("ITEM 1", 33),
            ("ITEM 7", 23),
            ("ITEM 16", 16),
            ("ITEM 2", 14),
        ),
        0.26,
        0.019,
    ),
    LocationSpec(
        "intangibles", 4, (("ITEM 8", 2), ("ITEM 1", 1), ("ITEM 16", 1)), 1.0, 0.0
    ),
    LocationSpec(
        "inventory",
        18,
        (("ITEM 1", 7), ("ITEM 8", 5), ("ITEM 16", 3), ("ITEM 7", 1), ("ITEM 4", 1)),
        0.889,
        0.0,
    ),
    LocationSpec(
        "lease_maturity",
        17,
        (("ITEM 8", 6), ("ITEM 16", 5), ("ITEM 1", 3), ("ITEM 5", 1), (None, 1)),
        0.824,
        0.059,
    ),
    LocationSpec(
        "other",
        6413,
        (
            ("ITEM 8", 1477),
            ("ITEM 1", 875),
            ("ITEM 15", 728),
            (None, 682),
            ("ITEM 7", 578),
        ),
        0.567,
        0.022,
    ),
    LocationSpec("pension", 4, (("ITEM 8", 2), ("ITEM 1", 2)), 1.0, 0.0),
    LocationSpec("ppe", 3, (("ITEM 1", 3)), 1.0, 0.0),
    LocationSpec("shares_purchased", 2, (("ITEM 1", 1), ("ITEM 15", 1)), 1.0, 0.0),
    LocationSpec(
        "stock_comp_rollforward",
        8,
        (("ITEM 16", 2), ("ITEM 1", 2), ("ITEM 5", 1), ("ITEM 15", 1), (None, 1)),
        0.75,
        0.125,
    ),
    LocationSpec(
        "tax_reconciliation",
        22,
        (("ITEM 16", 10), ("ITEM 8", 6), ("ITEM 15", 2), (None, 2), ("ITEM 7A", 1)),
        0.955,
        0.045,
    ),
)
