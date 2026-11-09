"""Section taxonomy for Form N-30D shareholder reports: the letter,
performance, and financial-statement sections filed specimens
evidence, in filed order.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition

FORM_N30D_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "LETTER TO SHAREHOLDERS",
        1,
        (
            "letter to shareholders",
            "letter to the shareholders",
            "president's letter",
            "chairman's letter",
            "message to shareholders",
            "dear shareholder",
        ),
        optional=True,
        early=True,
    ),
    ItemDefinition(
        "FUND PERFORMANCE",
        1,
        ("fund performance",),
        optional=True,
    ),
    ItemDefinition(
        "PORTFOLIO OF INVESTMENTS",
        1,
        (
            "portfolio of investments",
            "schedule of investments",
            "consolidated schedule of investments",
            "schedule of portfolio investments",
        ),
        optional=True,
    ),
    ItemDefinition(
        "STATEMENT OF ASSETS AND LIABILITIES",
        1,
        (
            "statement of assets and liabilities",
            "consolidated statement of assets and liabilities",
            "statement of net assets",
        ),
        optional=True,
    ),
    ItemDefinition(
        "STATEMENT OF OPERATIONS",
        1,
        (
            "statement of operations",
            "consolidated statement of operations",
        ),
        optional=True,
    ),
    ItemDefinition(
        "STATEMENTS OF CHANGES IN NET ASSETS",
        1,
        (
            "statements of changes in net assets",
            "statement of changes in net assets",
            "consolidated statement of changes in net assets",
        ),
        optional=True,
    ),
    ItemDefinition(
        "STATEMENT OF CASH FLOWS",
        1,
        (
            "statement of cash flows",
            "statements of cash flows",
        ),
        optional=True,
    ),
    ItemDefinition(
        "FINANCIAL HIGHLIGHTS",
        1,
        (
            "financial highlights",
            "per share operating performance",
        ),
        optional=True,
    ),
    ItemDefinition(
        "NOTES TO FINANCIAL STATEMENTS",
        1,
        (
            "notes to financial statements",
            "notes to the financial statements",
        ),
        optional=True,
    ),
    ItemDefinition(
        "REPORT OF INDEPENDENT REGISTERED PUBLIC ACCOUNTING FIRM",
        1,
        (
            "report of independent registered public accounting firm",
            "report of independent auditors",
            "independent auditors' report",
            "report of independent accountants",
        ),
        optional=True,
    ),
)

__all__ = ["FORM_N30D_ITEMS"]
