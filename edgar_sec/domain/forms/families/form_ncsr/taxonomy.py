"""Section taxonomy for Form N-CSR certified shareholder reports: the
financial-statement sections filed specimens evidence, in filed order.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition

FORM_NCSR_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "PORTFOLIO OF INVESTMENTS",
        1,
        (
            "portfolio of investments",
            "schedule of investments",
            "consolidated schedule of investments",
        ),
        early=True,
    ),
    ItemDefinition(
        "STATEMENT OF ASSETS AND LIABILITIES",
        1,
        ("statement of assets and liabilities",),
        optional=True,
    ),
    ItemDefinition(
        "STATEMENT OF OPERATIONS",
        1,
        ("statement of operations",),
        optional=True,
    ),
    ItemDefinition(
        "STATEMENTS OF CHANGES IN NET ASSETS",
        1,
        (
            "statements of changes in net assets",
            "statement of changes in net assets",
        ),
        optional=True,
    ),
    ItemDefinition(
        "FINANCIAL HIGHLIGHTS",
        1,
        ("financial highlights",),
        optional=True,
    ),
    ItemDefinition(
        "NOTES TO FINANCIAL STATEMENTS",
        1,
        ("notes to financial statements",),
        optional=True,
    ),
    ItemDefinition(
        "REPORT OF INDEPENDENT REGISTERED PUBLIC ACCOUNTING FIRM",
        1,
        ("report of independent registered public accounting firm",),
        optional=True,
    ),
)

__all__ = ["FORM_NCSR_ITEMS"]
