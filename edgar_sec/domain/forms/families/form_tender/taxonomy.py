"""Tender family item taxonomies per kind: Regulation M-A sets for the
modern schedules and the evidenced predecessor sets for the earlier lines.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition
from edgar_sec.domain.forms.families.form_tender.models import TenderKind

SCHEDULE_TO_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition("ITEM 1", 1, ("summary term sheet",)),
    ItemDefinition("ITEM 2", 1, ("subject company information",)),
    ItemDefinition(
        "ITEM 3",
        1,
        (
            "identity and background of filing person",
            "identity and background of filing persons",
        ),
    ),
    ItemDefinition("ITEM 4", 1, ("terms of the tender offer",)),
    ItemDefinition(
        "ITEM 5",
        1,
        (
            "past contacts, transactions, negotiations and agreements",
            "past contacts, transactions and negotiations",
        ),
    ),
    ItemDefinition(
        "ITEM 6",
        1,
        (
            "purposes of the tender offer and plans or proposals",
            "purposes of the tender offer, and plans or proposals",
            "purposes of the transaction and plans or proposals",
        ),
    ),
    ItemDefinition(
        "ITEM 7",
        1,
        (
            "source and amount of funds or other consideration",
            "source and amount of funds",
        ),
    ),
    ItemDefinition("ITEM 8", 1, ("interest in securities of the subject company",)),
    ItemDefinition(
        "ITEM 9",
        1,
        (
            "persons/assets retained, employed, compensated or used",
            "persons/assets, retained, employed, compensated or used",
            "persons or assets retained, employed, compensated or used",
        ),
    ),
    ItemDefinition("ITEM 10", 1, ("financial statements",)),
    ItemDefinition("ITEM 11", 1, ("additional information",)),
    ItemDefinition("ITEM 12", 1, ("exhibits", "materials to be filed as exhibits")),
    ItemDefinition("ITEM 13", 1, ("information required by schedule 13e-3",)),
)

SCHEDULE_14D9_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition("ITEM 1", 1, ("subject company information",)),
    ItemDefinition(
        "ITEM 2",
        1,
        (
            "identity and background of filing person",
            "identity and background of filing persons",
        ),
    ),
    ItemDefinition(
        "ITEM 3",
        1,
        (
            "past contacts, transactions, negotiations and agreements",
            "past contacts, transactions and negotiations",
        ),
    ),
    ItemDefinition(
        "ITEM 4",
        1,
        ("the solicitation or recommendation", "solicitation or recommendation"),
    ),
    ItemDefinition(
        "ITEM 5",
        1,
        (
            "person/assets retained, employed, compensated or used",
            "person/assets, retained, employed, compensated or used",
            "persons/assets retained, employed, compensated or used",
        ),
    ),
    ItemDefinition("ITEM 6", 1, ("interest in securities of the subject company",)),
    ItemDefinition(
        "ITEM 7",
        1,
        (
            "purposes of the transaction, plans or proposals",
            "purposes of the transaction and plans or proposals",
        ),
    ),
    ItemDefinition("ITEM 8", 1, ("additional information",)),
    ItemDefinition("ITEM 9", 1, ("exhibits", "materials to be filed as exhibits")),
)

SCHEDULE_13E3_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition("ITEM 1", 1, ("summary term sheet",)),
    ItemDefinition("ITEM 2", 1, ("subject company information",)),
    ItemDefinition(
        "ITEM 3",
        1,
        (
            "identity and background of filing persons",
            "identity and background of filing person",
        ),
    ),
    ItemDefinition("ITEM 4", 1, ("terms of the transaction",)),
    ItemDefinition(
        "ITEM 5",
        1,
        (
            "past contacts, transactions, negotiations and agreements",
            "past contacts, transactions and negotiations",
        ),
    ),
    ItemDefinition(
        "ITEM 6",
        1,
        (
            "purposes of the transaction, and plans or proposals",
            "purposes of the transaction and plans or proposals",
        ),
    ),
    ItemDefinition(
        "ITEM 7",
        1,
        (
            "purposes, alternatives, reasons and effects",
            "purposes, alternatives, reasons, and effects",
        ),
    ),
    ItemDefinition("ITEM 8", 1, ("fairness of the transaction",)),
    ItemDefinition(
        "ITEM 9",
        1,
        (
            "reports, opinions, appraisals and negotiations",
            "reports, opinions, appraisals and certain negotiations",
        ),
    ),
    ItemDefinition(
        "ITEM 10",
        1,
        (
            "source and amounts of funds or other consideration",
            "source and amount of funds or other consideration",
        ),
    ),
    ItemDefinition("ITEM 11", 1, ("interest in securities of the subject company",)),
    ItemDefinition(
        "ITEM 12",
        1,
        ("the solicitation or recommendation", "solicitation or recommendation"),
    ),
    ItemDefinition("ITEM 13", 1, ("financial statements", "financial information")),
    ItemDefinition(
        "ITEM 14",
        1,
        (
            "persons/assets, retained, employed, compensated or used",
            "persons/assets retained, employed, compensated or used",
        ),
    ),
    ItemDefinition("ITEM 15", 1, ("additional information",)),
    ItemDefinition("ITEM 16", 1, ("exhibits", "materials to be filed as exhibits")),
)

SCHEDULE_13E3_PRIOR_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "ITEM 1", 1, ("issuer and class of security subject to the transaction",)
    ),
    ItemDefinition("ITEM 2", 1, ("identity and background",)),
    ItemDefinition(
        "ITEM 3",
        1,
        (
            "past contacts, transactions or negotiations",
            "past contacts, transactions, negotiations",
        ),
    ),
    ItemDefinition("ITEM 4", 1, ("terms of the transaction",)),
    ItemDefinition("ITEM 5", 1, ("plans or proposals of the issuer or affiliate",)),
    ItemDefinition(
        "ITEM 6",
        1,
        (
            "source and amounts of funds or other consideration",
            "source and amounts of funds",
        ),
    ),
    ItemDefinition(
        "ITEM 7",
        1,
        (
            "purpose(s), alternatives, reasons and effects",
            "purposes, alternatives, reasons and effects",
        ),
    ),
    ItemDefinition("ITEM 8", 1, ("fairness of the transaction",)),
    ItemDefinition(
        "ITEM 9",
        1,
        (
            "reports, opinions, appraisals and certain negotiations",
            "reports, opinions, appraisals and negotiations",
        ),
    ),
    ItemDefinition("ITEM 10", 1, ("interest in securities of the issuer",)),
    ItemDefinition(
        "ITEM 11",
        1,
        (
            "contracts, arrangements or understandings with respect to securities of the issuer",
            "contracts, arrangements, understandings or relationships with respect to securities of the issuer",
        ),
    ),
    ItemDefinition(
        "ITEM 12", 1, ("present intention and recommendation of certain persons",)
    ),
    ItemDefinition(
        "ITEM 13",
        1,
        ("other provisions of the transaction", "other provisions of the offer"),
    ),
    ItemDefinition("ITEM 14", 1, ("financial information", "financial statements")),
    ItemDefinition(
        "ITEM 15",
        1,
        (
            "persons or assets employed, retained or utilized",
            "persons/assets, retained, employed, compensated or used",
        ),
    ),
    ItemDefinition("ITEM 16", 1, ("additional information",)),
    ItemDefinition("ITEM 17", 1, ("material to be filed as exhibits", "exhibits")),
)

SCHEDULE_13E4_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition("ITEM 1", 1, ("security and issuer",)),
    ItemDefinition("ITEM 2", 1, ("source and amount of funds or other consideration",)),
    ItemDefinition(
        "ITEM 3",
        1,
        (
            "purpose of the tender offer and plans or proposals of the issuer",
            "purpose of the tender offer",
        ),
    ),
    ItemDefinition("ITEM 4", 1, ("interest in securities of the issuer",)),
    ItemDefinition(
        "ITEM 5",
        1,
        (
            "contracts, arrangements, understandings or relationships with respect to securities of the issuer",
            "contracts, arrangements, understandings or relationships",
        ),
    ),
    ItemDefinition("ITEM 6", 1, ("persons retained, employed or to be compensated",)),
    ItemDefinition("ITEM 7", 1, ("financial information",)),
    ItemDefinition("ITEM 8", 1, ("additional information",)),
    ItemDefinition("ITEM 9", 1, ("material to be filed as exhibits", "exhibits")),
)

SCHEDULE_14D1_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition("ITEM 1", 1, ("security and subject company",)),
    ItemDefinition("ITEM 2", 1, ("identity and background",)),
    ItemDefinition(
        "ITEM 3",
        1,
        (
            "past contacts, transactions or negotiations with the subject company",
            "past contacts, transactions or negotiations",
        ),
    ),
    ItemDefinition("ITEM 4", 1, ("source and amount of funds or other consideration",)),
    ItemDefinition(
        "ITEM 5",
        1,
        (
            "purpose of the tender offer and plans or proposals of the bidder",
            "purpose of the tender offer",
        ),
    ),
    ItemDefinition("ITEM 6", 1, ("interest in securities of the subject company",)),
    ItemDefinition(
        "ITEM 7",
        1,
        (
            "contracts, arrangements, understandings or relationships with respect to securities of the subject company",
            "contracts, arrangements, understandings or relationships",
        ),
    ),
    ItemDefinition("ITEM 8", 1, ("persons retained, employed or to be compensated",)),
    ItemDefinition(
        "ITEM 9", 1, ("financial statements of bidders", "financial statements")
    ),
    ItemDefinition("ITEM 10", 1, ("additional information",)),
    ItemDefinition("ITEM 11", 1, ("material to be filed as exhibits", "exhibits")),
)

SCHEDULE_14D1F_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition("ITEM 1", 1, ("home jurisdiction documents",)),
    ItemDefinition("ITEM 2", 1, ("informational legends",)),
)

#: Taxonomy per kind where the kind alone determines the set; the
#: going-private kind resolves among its three sets by cover face.
TENDER_TAXONOMY_BY_KIND: dict[TenderKind, tuple[ItemDefinition, ...]] = {
    TenderKind.SCHEDULE_TO: SCHEDULE_TO_ITEMS,
    TenderKind.SOLICITATION: SCHEDULE_14D9_ITEMS,
    TenderKind.GOING_PRIVATE: SCHEDULE_13E3_ITEMS,
    TenderKind.ISSUER_TENDER_PREDECESSOR: SCHEDULE_13E4_ITEMS,
    TenderKind.THIRD_PARTY_PREDECESSOR: SCHEDULE_14D1_ITEMS,
    TenderKind.FOREIGN_NOTICE: SCHEDULE_14D1F_ITEMS,
}

TENDER_TITLES: tuple[str, ...] = (
    "schedule to",
    "tender offer statement",
    "schedule 14d-9",
    "solicitation/recommendation statement",
    "schedule 13e-3",
    "rule 13e-3 transaction statement",
    "schedule 13e-4",
    "issuer tender offer statement",
    "schedule 14d-1",
    "schedule 14d-1f",
)

__all__ = [
    "SCHEDULE_13E3_ITEMS",
    "SCHEDULE_13E3_PRIOR_ITEMS",
    "SCHEDULE_13E4_ITEMS",
    "SCHEDULE_14D1F_ITEMS",
    "SCHEDULE_14D1_ITEMS",
    "SCHEDULE_14D9_ITEMS",
    "SCHEDULE_TO_ITEMS",
    "TENDER_TAXONOMY_BY_KIND",
    "TENDER_TITLES",
]
