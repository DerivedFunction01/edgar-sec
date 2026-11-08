"""Section taxonomy for Form 18-K annual reports of foreign governments
and their agencies: the sections filed specimens evidence, in filed order.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition

FORM_18K_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "EXPLANATORY NOTE",
        1,
        ("explanatory note",),
        optional=True,
        early=True,
    ),
    ItemDefinition(
        "PRESENTATION OF FINANCIAL AND OTHER INFORMATION",
        1,
        ("presentation of financial and other information",),
        optional=True,
    ),
    ItemDefinition(
        "RECENT DEVELOPMENTS",
        1,
        (
            "recent developments",
            "other recent developments",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ECONOMY",
        1,
        (
            "economy",
            "the economy",
        ),
        optional=True,
    ),
    ItemDefinition(
        "PUBLIC FINANCE",
        1,
        ("public finance",),
        optional=True,
    ),
    ItemDefinition(
        "CAPITALIZATION AND INDEBTEDNESS",
        1,
        (
            "capitalization and indebtedness",
            "short-term indebtedness and capitalization",
            "public debt",
            "indebtedness",
        ),
        optional=True,
    ),
    ItemDefinition(
        "FINANCIAL STATEMENTS",
        1,
        (
            "financial statements",
            "consolidated financial statements",
            "financial section",
        ),
        optional=True,
    ),
    ItemDefinition(
        "BALANCE SHEET",
        1,
        (
            "balance sheet",
            "consolidated balance sheet",
            "statement of financial position",
            "bilan",
        ),
        optional=True,
    ),
    ItemDefinition(
        "INCOME STATEMENT",
        1,
        (
            "income statement",
            "statement of income",
            "statement of operations",
            "consolidated statement of income",
            "consolidated statements of income",
        ),
        optional=True,
    ),
    ItemDefinition(
        "STATEMENT OF CASH FLOWS",
        1,
        (
            "statement of cash flows",
            "cash flow statement",
            "consolidated statement of cash flows",
            "consolidated statements of cash flows",
        ),
        optional=True,
    ),
    ItemDefinition(
        "NOTES TO FINANCIAL STATEMENTS",
        1,
        (
            "notes to financial statements",
            "notes to the financial statements",
            "notes to consolidated financial statements",
        ),
        optional=True,
    ),
    ItemDefinition(
        "EXHIBIT INDEX",
        1,
        (
            "exhibit index",
            "index to exhibits",
            "exhibits",
        ),
        optional=True,
    ),
    ItemDefinition(
        "SIGNATURES",
        1,
        (
            "signatures",
            "signature",
            "signature page",
        ),
        optional=True,
    ),
)

__all__ = ["FORM_18K_ITEMS"]
