"""Item taxonomy for Schedule 14A proxy and information statements."""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition

FORM_14A_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "ITEM 1",
        1,
        (
            "date, time and place of meeting",
            "date, time, and place of meeting",
        ),
    ),
    ItemDefinition(
        "ITEM 2",
        1,
        ("revocability of proxy",),
    ),
    ItemDefinition(
        "ITEM 3",
        1,
        (
            "dissenters' right of appraisal",
            "dissenters' rights of appraisal",
            "appraisal rights",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 4",
        1,
        (
            "persons making the solicitation",
            "participants in the solicitation",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 5",
        1,
        (
            "interest of certain persons in matters to be acted upon",
            "interests of certain persons in matters to be acted upon",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 6",
        1,
        (
            "voting securities and principal holders thereof",
            "security ownership of certain beneficial owners and management",
            "security ownership of management and principal stockholders",
        ),
    ),
    ItemDefinition(
        "ITEM 7",
        1,
        (
            "directors and executive officers",
            "election of directors",
            "election of director nominees",
            "director nominees",
        ),
    ),
    ItemDefinition(
        "ITEM 8",
        1,
        (
            "compensation of directors and executive officers",
            "executive compensation",
            "compensation discussion and analysis",
        ),
    ),
    ItemDefinition(
        "ITEM 9",
        1,
        (
            "independent public accountants",
            "independent registered public accounting firm",
            "principal accountant fees and services",
            "audit and non-audit fees",
        ),
    ),
    ItemDefinition(
        "ITEM 10",
        1,
        ("compensation plans",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 11",
        1,
        (
            "authorization or issuance of securities otherwise than for exchange",
            "authorization or issuance of securities otherwise than for exchange or in connection with an acquisition",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 12",
        1,
        ("modification or exchange of securities",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 13",
        1,
        ("financial and other information",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 14",
        1,
        (
            "corporate governance",
            "corporate governance and board matters",
            "corporate governance matters",
        ),
    ),
    ItemDefinition(
        "ITEM 15",
        1,
        ("accounts and reports of the committee",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 16",
        1,
        (
            "amendments to charter, bylaws or other documents",
            "amendments to charter or bylaws",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 17",
        1,
        ("capitalization",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 18",
        1,
        (
            "issuance of debt with maturity of more than one year",
            "issuance of debt with maturity of more than one year to refinance or refund outstanding debt",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 19",
        1,
        (
            "borrowing money — other than in the ordinary course of business",
            "borrowing money - other than in the ordinary course of business",
            "borrowing money other than in the ordinary course of business",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 20",
        1,
        (
            "other proposed action",
            "other business",
            "other matters",
        ),
    ),
    ItemDefinition(
        "ITEM 21",
        1,
        (
            "voting procedures",
            "voting and proxy procedures",
            "general information about voting",
        ),
    ),
    ItemDefinition(
        "ITEM 22",
        1,
        (
            "information required in investment company proxy statement",
            "information required in investment company proxy statements",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 23",
        1,
        (
            "delivery of documents to security holders sharing an address",
            "householding of proxy materials",
            "household delivery of proxy materials",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 24",
        1,
        (
            "shareholder approval of executive compensation",
            "advisory vote on executive compensation",
            "advisory vote to approve executive compensation",
            "say on pay",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 25",
        1,
        ("exhibits",),
        optional=True,
    ),
)

FORM_14A_TITLES: tuple[str, ...] = (
    "schedule 14a",
    "schedule 14a information",
    "proxy statement",
    "information statement",
)

__all__ = [
    "FORM_14A_ITEMS",
    "FORM_14A_TITLES",
]
