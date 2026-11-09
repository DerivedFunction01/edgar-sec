"""Section taxonomy for Form N-VP variable-product filings: the
notice-document sections and the financial-statements block filed
specimens evidence, in filed order.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition

FORM_NVP_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "UPDATED INFORMATION",
        1,
        (
            "updated information about your contract",
            "updated information about your policy",
            "updated information",
        ),
        optional=True,
        early=True,
    ),
    ItemDefinition(
        "KEY INFORMATION",
        1,
        (
            "key information",
            "important information you should consider about the contract",
            "important information you should consider about the policy",
            "important information you should consider",
        ),
        optional=True,
        early=True,
    ),
    ItemDefinition(
        "FEES AND EXPENSES",
        1,
        ("fees and expenses",),
        optional=True,
    ),
    ItemDefinition(
        "RISKS",
        1,
        ("risks",),
        optional=True,
    ),
    ItemDefinition(
        "RESTRICTIONS",
        1,
        ("restrictions",),
        optional=True,
    ),
    ItemDefinition(
        "TAXES",
        1,
        ("taxes",),
        optional=True,
    ),
    ItemDefinition(
        "CONFLICTS OF INTEREST",
        1,
        ("conflicts of interest",),
        optional=True,
    ),
    ItemDefinition(
        "REPORT OF INDEPENDENT REGISTERED PUBLIC ACCOUNTING FIRM",
        1,
        (
            "report of independent registered public accounting firm",
            "report of independent registered public accounting",
        ),
        optional=True,
    ),
    ItemDefinition(
        "STATEMENT OF ASSETS AND LIABILITIES",
        1,
        (
            "statements of assets and liabilities",
            "statement of assets and liabilities",
        ),
        optional=True,
    ),
    ItemDefinition(
        "STATEMENT OF OPERATIONS",
        1,
        (
            "statements of operations",
            "statement of operations",
        ),
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
        "NOTES TO FINANCIAL STATEMENTS",
        1,
        (
            "notes to financial statements",
            "notes to the financial statements",
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
        "APPENDIX: PORTFOLIOS AVAILABLE",
        1,
        (
            "appendix: portfolios available under the contract",
            "appendix: portfolios available under the policy",
            "portfolios available under the contract",
            "portfolios available under the policy",
        ),
        optional=True,
    ),
)

__all__ = ["FORM_NVP_ITEMS"]
