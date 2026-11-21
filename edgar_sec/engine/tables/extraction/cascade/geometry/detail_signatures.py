"""Detail signatures and their scored vetoes (Deliverable 1 sets).

Named detail shapes a summary family never carries, matched over
stub + caption text; the competition applies the scored-veto
penalty to a family whose vetoed signatures fired.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from edgar_sec.engine.tables.extraction.core.text.normalize import normalize_text
from edgar_sec.foundation.text.dates import YEAR_TOKEN_SEARCH_RE

if TYPE_CHECKING:
    from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
        GeometryText,
    )


# Detail signatures: named detail shapes a summary family never
# carries, matched over stub + caption text (Deliverable 1 sets).
DETAIL_SIGNATURES: dict[str, tuple[str, ...]] = {
    "maturity_buckets": (
        "thereafter",
        "less than 1 year",
        "1 to 2 years",
        "2 to 3 years",
        "3 to 4 years",
        "4 to 5 years",
        "more than 5 years",
        "fiscal year ending",
        "years ending december",
    ),
    "rollforward_movement": (
        "beginning balance",
        "beginning of year",
        "beginning of period",
        "ending balance",
        "end of year",
        "end of period",
        "additions",
        "deductions",
        "settlements",
        "curtailments",
    ),
    "period_columns": (
        "three months ended",
        "six months ended",
        "nine months ended",
        "year ended",
        "years ended",
        "quarter ended",
    ),
    "supplemental_schedule": (
        "supplemental",
        "schedule of",
        "noncash",
        "non-cash",
    ),
    "grant_activity": (
        "granted",
        "exercised",
        "forfeited",
        "vested",
        "unvested",
        "shares authorized",
        "options outstanding",
        "shares available",
    ),
    "composition_detail": (
        "valuation allowance",
        "net deferred tax",
        "gross deferred tax",
        "tax effect of",
        "deferred tax assets",
        "deferred tax liabilities",
    ),
    "percentage_rows": (
        "% of",
        "percentage of",
        "percent of",
        "as a percentage",
    ),
    "segment_detail": (
        "total segment",
        "corporate and other",
        "eliminations",
        "segment profit",
        "segment revenue",
        "operating segments",
    ),
    "acquisition_detail": (
        "purchase price",
        "consideration transferred",
        "identifiable assets acquired",
        "goodwill recognized",
        "acquisition date",
    ),
}
# The scored class of the Deliverable 1 veto pricing: family ->
# signatures whose kill rate beat member collateral by the rule.
SCORED_VETOES: dict[str, tuple[str, ...]] = {
    "balance_sheet": (
        "acquisition_detail",
        "period_columns",
        "rollforward_movement",
    ),
    "comprehensive_income": ("year_columns",),
    "deferred_tax": ("period_columns",),
    "equity_statement": ("composition_detail",),
    "income_statement": ("rollforward_movement", "segment_detail"),
    "intangibles": (
        "maturity_buckets",
        "percentage_rows",
        "period_columns",
        "year_columns",
    ),
    "stock_comp_rollforward": ("period_columns",),
}


def detail_signatures(geometry: GeometryText) -> set[str]:
    """The named detail signatures present in stub + caption text."""
    text = geometry.stub_text + " " + normalize_text(geometry.caption)
    found = {
        name
        for name, terms in DETAIL_SIGNATURES.items()
        if any(term in text for term in terms)
    }
    years = set(YEAR_TOKEN_SEARCH_RE.findall(geometry.stub_text))
    if len(years) >= 2:
        found.add("year_columns")
    return found
