"""Deferred tax seat spec data: the priced leg vocabulary.

The phrase tuples of the R18 depth-1/depth-2 instruments,
carried verbatim as data for deferred_tax_seat.py.
"""

from __future__ import annotations

MARKERS = (
    "total",
    "net deferred",
    "valuation allowance",
    "deferred tax assets",
    "deferred tax liabilities",
    "deferred income tax",
    "temporary differences",
)
DTA_TERMS = ("deferred tax assets", "deferred income tax assets")
DTL_TERMS = ("deferred tax liabilities", "deferred income tax liabilities")
VAL_ALLOW_TERMS = ("valuation allowance",)
NET_TERMS = ("net deferred tax", "net deferred income tax")
TOTAL_TERMS = (
    "total deferred tax assets",
    "total deferred tax liabilities",
    "total deferred income tax",
)
TEMP_DIFF_TERMS = ("temporary differences",)
HEADER_TERMS = ("deferred tax", "deferred income tax")
WALK_ROW_TERMS = ("balance", "at beginning", "at end of")
A4_STUB_TERMS = ("deferred", "income tax")
PERIOD_TERMS = ("at beginning of period", "at end of period")
A5_STUB_TERM = "deferred tax asset"
