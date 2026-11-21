"""Section taxonomy for Form 497 prospectus filings: the prospectus
sections filed specimens evidence, shared with the prospectus cluster.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition

FORM_497_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "SUMMARY",
        1,
        (
            "summary",
            "prospectus summary",
            "investment objective",
        ),
        early=True,
    ),
    ItemDefinition(
        "RISK FACTORS",
        1,
        (
            "risk factors",
            "principal risks",
            "risks",
        ),
        optional=True,
    ),
    ItemDefinition(
        "USE OF PROCEEDS",
        1,
        ("use of proceeds",),
        optional=True,
    ),
    ItemDefinition(
        "PLAN OF DISTRIBUTION",
        1,
        ("plan of distribution",),
        optional=True,
    ),
    ItemDefinition(
        "UNDERWRITING",
        1,
        (
            "underwriting",
            "underwriters",
        ),
        optional=True,
    ),
    ItemDefinition(
        "LEGAL MATTERS",
        1,
        ("legal matters",),
        optional=True,
    ),
)

__all__ = ["FORM_497_ITEMS"]
