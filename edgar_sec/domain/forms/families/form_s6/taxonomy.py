"""Section taxonomy for Form S-6 unit investment trust registrations:
the prospectus sections filed specimens evidence, in filed order.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition

FORM_S6_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "SUMMARY OF ESSENTIAL INFORMATION",
        1,
        (
            "summary of essential information",
            "investment summary",
        ),
        early=True,
    ),
    ItemDefinition(
        "FEE TABLE",
        1,
        ("fee table",),
        optional=True,
        early=True,
    ),
    ItemDefinition(
        "AUDITORS REPORT",
        1,
        (
            "report of independent registered public accounting firm",
            "report of independent auditors",
            "report of independent public accountants",
        ),
        optional=True,
    ),
    ItemDefinition(
        "STATEMENT OF NET ASSETS",
        1,
        (
            "statement of net assets",
            "statement of financial condition",
            "statement of condition",
        ),
        optional=True,
    ),
    ItemDefinition(
        "SCHEDULE OF INVESTMENTS",
        1,
        (
            "schedule of investments",
            "schedule of portfolio investments",
        ),
        optional=True,
    ),
    ItemDefinition(
        "PORTFOLIO",
        1,
        ("portfolio",),
        optional=True,
    ),
    ItemDefinition(
        "RISK FACTORS",
        1,
        (
            "risk factors",
            "principal risks",
        ),
        optional=True,
    ),
    ItemDefinition(
        "PUBLIC OFFERING",
        1,
        (
            "public offering",
            "public sale of units",
        ),
        optional=True,
    ),
    ItemDefinition(
        "DISTRIBUTION OF UNITS",
        1,
        ("distribution of units",),
        optional=True,
    ),
    ItemDefinition(
        "UNDERWRITING",
        1,
        (
            "underwriting",
            "underwriting concessions",
        ),
        optional=True,
    ),
    ItemDefinition(
        "EXPENSES AND CHARGES",
        1,
        (
            "expenses and charges",
            "trust expenses and charges",
        ),
        optional=True,
    ),
    ItemDefinition(
        "TAX STATUS",
        1,
        (
            "tax status",
            "federal tax status",
            "tax consequences",
        ),
        optional=True,
    ),
    ItemDefinition(
        "RIGHTS OF UNIT HOLDERS",
        1,
        (
            "rights of unit holders",
            "rights of unitholders",
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
)

__all__ = ["FORM_S6_ITEMS"]
