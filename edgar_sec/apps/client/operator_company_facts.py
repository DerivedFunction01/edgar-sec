"""The company operation's facts cross-check section.

The resolved company's SEC-reported facts are compared against its
latest filing's instance-parsed values over the standardised concept
set; the section renders the comparison's four outcome classes.
"""

from __future__ import annotations

from typing import Any

from edgar_sec.apps.client.companyfacts import (
    compare_company_facts_to_parsed,
    parsed_values_by_key,
)

__all__ = [
    "FACTS_CHECK_CONCEPTS",
    "facts_check_section",
]

FACTS_CHECK_CONCEPTS: tuple[tuple[str, str, str], ...] = (
    ("us-gaap", "Assets", "USD"),
    ("us-gaap", "Liabilities", "USD"),
    ("us-gaap", "StockholdersEquity", "USD"),
    ("us-gaap", "CashAndCashEquivalentsAtCarryingValue", "USD"),
    ("us-gaap", "NetIncomeLoss", "USD"),
    ("us-gaap", "Revenues", "USD"),
    ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax", "USD"),
    ("us-gaap", "SalesRevenueNet", "USD"),
    ("us-gaap", "NetCashProvidedByUsedInOperatingActivities", "USD"),
    ("dei", "EntityCommonStockSharesOutstanding", "shares"),
)
_FACTS_CHECK_ROWS = 50


def facts_check_section(company: Any, session: Any, cik: str) -> dict[str, Any]:
    """Cross-check one resolved company; ``cik`` is its 10-digit text."""
    facts = session.facade.company_facts(cik)
    surface = company.xbrl()
    parsed = parsed_values_by_key(surface.facts if surface is not None else ())
    comparison = compare_company_facts_to_parsed(
        facts, parsed, concepts=set(FACTS_CHECK_CONCEPTS)
    )
    rows = [
        {
            "taxonomy": row.key.taxonomy,
            "tag": row.key.tag,
            "unit": row.key.unit,
            "start": row.key.start,
            "end": row.key.end,
            "outcome": row.outcome,
            "facts_value": row.facts_value,
            "parsed_value": row.parsed_value,
            "accession": row.accession,
        }
        for row in comparison.rows
    ]
    return {
        "cik": cik,
        "cross_check": True,
        "provenance": "SEC-reported company facts vs instance-parsed values",
        "counts": comparison.counts,
        "agreement_rate": comparison.agreement_rate,
        "total": len(rows),
        "shown": min(len(rows), _FACTS_CHECK_ROWS),
        "rows": rows[:_FACTS_CHECK_ROWS],
    }
