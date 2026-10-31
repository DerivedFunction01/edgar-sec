"""Part and Item taxonomy for registration statements (Form S-1)."""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition
from edgar_sec.domain.forms.families.annual.taxonomy import build_taxonomy_derived

PARTS: tuple[str, ...] = ("PART I", "PART II")

FORM_S1_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "ITEM 1",
        1,
        (
            "forepart of the registration statement and outside front cover page of prospectus",
            "outside front cover page of prospectus",
            "front cover page of prospectus",
        ),
        early=True,
    ),
    ItemDefinition(
        "ITEM 2",
        1,
        (
            "inside front and outside back cover pages of prospectus",
            "inside front and outside back cover pages",
        ),
        optional=True,
        early=True,
    ),
    ItemDefinition(
        "ITEM 3",
        1,
        (
            "summary information, risk factors and ratio of earnings to fixed charges",
            "summary information and risk factors",
            "prospectus summary",
            "summary",
            "risk factors",
        ),
        early=True,
    ),
    ItemDefinition(
        "ITEM 4",
        1,
        ("use of proceeds",),
        early=True,
    ),
    ItemDefinition(
        "ITEM 5",
        1,
        ("determination of offering price",),
        early=True,
    ),
    ItemDefinition(
        "ITEM 6",
        1,
        ("dilution",),
        early=True,
    ),
    ItemDefinition(
        "ITEM 7",
        1,
        ("selling security holders", "selling stockholders", "selling shareholders"),
        optional=True,
        early=True,
    ),
    ItemDefinition(
        "ITEM 8",
        1,
        ("plan of distribution", "underwriting"),
        early=True,
    ),
    ItemDefinition(
        "ITEM 9",
        1,
        (
            "description of securities to be registered",
            "description of capital stock",
            "description of securities",
        ),
    ),
    ItemDefinition(
        "ITEM 10",
        1,
        (
            "interests of named experts and counsel",
            "legal matters",
            "experts",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 11",
        1,
        (
            "information with respect to the registrant",
            "business",
            "description of business",
            "management's discussion and analysis of financial condition and results of operations",
            "financial statements",
        ),
    ),
    ItemDefinition(
        "ITEM 11A",
        1,
        ("material changes",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 12",
        1,
        (
            "incorporation of certain information by reference",
            "incorporation by reference",
            "where you can find more information",
            "where you can find additional information",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 12A",
        1,
        (
            "disclosure of commission position on indemnification for securities act liabilities",
            "disclosure of commission position on indemnification",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 13",
        2,
        (
            "other expenses of issuance and distribution",
            "expenses of issuance and distribution",
        ),
    ),
    ItemDefinition(
        "ITEM 14",
        2,
        ("indemnification of directors and officers",),
    ),
    ItemDefinition(
        "ITEM 15",
        2,
        (
            "recent sales of unregistered securities",
            "sales of unregistered securities",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 16",
        2,
        (
            "exhibits and financial statement schedules",
            "exhibits",
            "index to exhibits",
            "exhibit index",
        ),
    ),
    ItemDefinition(
        "ITEM 17",
        2,
        ("undertakings",),
    ),
)

FORM_S3_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "ITEM 1",
        1,
        (
            "forepart of the registration statement and outside front cover page of prospectus",
            "outside front cover page of prospectus",
            "front cover page of prospectus",
        ),
        early=True,
    ),
    ItemDefinition(
        "ITEM 2",
        1,
        (
            "inside front and outside back cover pages of prospectus",
            "inside front and outside back cover pages",
        ),
        optional=True,
        early=True,
    ),
    ItemDefinition(
        "ITEM 3",
        1,
        (
            "summary information, risk factors and ratio of earnings to fixed charges",
            "summary information and risk factors",
            "prospectus summary",
            "summary",
            "risk factors",
        ),
        early=True,
    ),
    ItemDefinition(
        "ITEM 4",
        1,
        ("use of proceeds",),
        early=True,
    ),
    ItemDefinition(
        "ITEM 5",
        1,
        ("determination of offering price",),
        early=True,
    ),
    ItemDefinition(
        "ITEM 6",
        1,
        ("dilution",),
        early=True,
    ),
    ItemDefinition(
        "ITEM 7",
        1,
        ("selling security holders", "selling stockholders", "selling shareholders"),
        optional=True,
        early=True,
    ),
    ItemDefinition(
        "ITEM 8",
        1,
        ("plan of distribution", "underwriting"),
        early=True,
    ),
    ItemDefinition(
        "ITEM 9",
        1,
        (
            "description of securities to be registered",
            "description of capital stock",
            "description of securities",
        ),
    ),
    ItemDefinition(
        "ITEM 10",
        1,
        (
            "interests of named experts and counsel",
            "legal matters",
            "experts",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 11",
        1,
        (
            "material changes",
            "material changes in the registrant's affairs",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 12",
        1,
        (
            "incorporation of certain information by reference",
            "incorporation by reference",
            "where you can find more information",
            "where you can find additional information",
        ),
    ),
    ItemDefinition(
        "ITEM 12A",
        1,
        (
            "disclosure of commission position on indemnification for securities act liabilities",
            "disclosure of commission position on indemnification",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 14",
        2,
        (
            "other expenses of issuance and distribution",
            "expenses of issuance and distribution",
        ),
    ),
    ItemDefinition(
        "ITEM 15",
        2,
        ("indemnification of directors and officers",),
    ),
    ItemDefinition(
        "ITEM 16",
        2,
        (
            "exhibits and financial statement schedules",
            "exhibits",
            "index to exhibits",
            "exhibit index",
        ),
    ),
    ItemDefinition(
        "ITEM 17",
        2,
        ("undertakings",),
    ),
)

FORM_S4_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "ITEM 1",
        1,
        (
            "forepart of registration statement and outside front cover page of prospectus",
            "outside front cover page of prospectus",
            "front cover page of prospectus",
        ),
        early=True,
    ),
    ItemDefinition(
        "ITEM 2",
        1,
        (
            "inside front and outside back cover pages of prospectus",
            "inside front and outside back cover pages",
        ),
        optional=True,
        early=True,
    ),
    ItemDefinition(
        "ITEM 3",
        1,
        (
            "risk factors, ratio of earnings to fixed charges and other information",
            "summary",
            "risk factors",
        ),
        early=True,
    ),
    ItemDefinition(
        "ITEM 4",
        1,
        (
            "terms of the transaction",
            "the merger",
            "the transaction",
        ),
        early=True,
    ),
    ItemDefinition(
        "ITEM 5",
        1,
        (
            "pro forma financial information",
            "unaudited pro forma financial information",
        ),
        early=True,
    ),
    ItemDefinition(
        "ITEM 6",
        1,
        (
            "material contracts with the company being acquired",
            "material contracts",
        ),
        optional=True,
        early=True,
    ),
    ItemDefinition(
        "ITEM 7",
        1,
        (
            "additional information required for reoffering by persons and parties deemed to be underwriters",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 8",
        1,
        (
            "interests of named experts and counsel",
            "legal matters",
            "experts",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 9",
        1,
        (
            "disclosure of commission position on indemnification for securities act liabilities",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 10",
        1,
        ("information with respect to s-3 registrants",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 11",
        1,
        ("incorporation of certain information by reference",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 12",
        1,
        ("information with respect to s-2 or s-3 registrants",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 13",
        1,
        ("incorporation of certain information by reference",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 14",
        1,
        ("information with respect to registrants other than s-3 or s-2 registrants",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 15",
        1,
        ("information with respect to s-3 companies",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 16",
        1,
        ("information with respect to s-2 or s-3 companies",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 17",
        1,
        ("information with respect to companies other than s-3 or s-2 companies",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 18",
        1,
        (
            "information if proxies, consents or authorizations are to be solicited",
            "voting and management information",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 19",
        1,
        (
            "information if proxies, consents or authorizations are not to be solicited or in an exchange offer",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 20",
        2,
        ("indemnification of directors and officers",),
    ),
    ItemDefinition(
        "ITEM 21",
        2,
        (
            "exhibits and financial statement schedules",
            "exhibits",
            "index to exhibits",
            "exhibit index",
        ),
    ),
    ItemDefinition(
        "ITEM 22",
        2,
        ("undertakings",),
    ),
)

FORM_S8_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "ITEM 1",
        1,
        ("plan information",),
        optional=True,
        early=True,
    ),
    ItemDefinition(
        "ITEM 2",
        1,
        ("registrant information and employee annual information",),
        optional=True,
        early=True,
    ),
    ItemDefinition(
        "ITEM 3",
        2,
        (
            "incorporation of documents by reference",
            "incorporation of certain documents by reference",
        ),
        early=True,
    ),
    ItemDefinition(
        "ITEM 4",
        2,
        ("description of securities",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 5",
        2,
        (
            "interests of named experts and counsel",
            "legal matters",
            "experts",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 6",
        2,
        ("indemnification of directors and officers",),
    ),
    ItemDefinition(
        "ITEM 7",
        2,
        ("exemption from registration claimed",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 8",
        2,
        (
            "exhibits",
            "index to exhibits",
            "exhibit index",
        ),
    ),
    ItemDefinition(
        "ITEM 9",
        2,
        ("undertakings",),
    ),
)

ITEMS: dict[str, str] = {d.item: d.names[0].title() for d in FORM_S1_ITEMS}

FORM_S1_DERIVED = build_taxonomy_derived(FORM_S1_ITEMS, PARTS)
FORM_S3_DERIVED = build_taxonomy_derived(FORM_S3_ITEMS, PARTS)
FORM_S4_DERIVED = build_taxonomy_derived(FORM_S4_ITEMS, PARTS)
FORM_S8_DERIVED = build_taxonomy_derived(FORM_S8_ITEMS, PARTS)

__all__ = [
    "FORM_S1_DERIVED",
    "FORM_S1_ITEMS",
    "FORM_S3_DERIVED",
    "FORM_S3_ITEMS",
    "FORM_S4_DERIVED",
    "FORM_S4_ITEMS",
    "FORM_S8_DERIVED",
    "FORM_S8_ITEMS",
    "ITEMS",
    "PARTS",
]
