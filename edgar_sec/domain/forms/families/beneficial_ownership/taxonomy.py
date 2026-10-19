from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition

SCHEDULE_13D_SUBMISSION_TYPES = frozenset({"SCHEDULE 13D", "SCHEDULE 13D/A"})
SCHEDULE_13G_SUBMISSION_TYPES = frozenset({"SCHEDULE 13G", "SCHEDULE 13G/A"})
SCHEDULE_LIVE_TEST_TYPES = frozenset({"LIVE", "TEST"})
SCHEDULE_13D_MEMBER_TYPES = frozenset({"a", "b"})
SCHEDULE_13D_FUND_TYPES = frozenset({"SC", "BK", "AF", "WC", "PF", "OO"})
SCHEDULE_13D_REPORTING_PERSON_TYPES = frozenset(
    {"BD", "BK", "CP", "CO", "EP", "IN", "IA", "IC", "IV", "HC", "PN", "SA", "OO"}
)
SCHEDULE_13G_RULE_TYPES = frozenset({"Rule 13d-1(b)", "Rule 13d-1(c)", "Rule 13d-1(d)"})
SCHEDULE_13G_GROUP_TYPES = frozenset({"a", "b"})
SCHEDULE_13G_REPORTING_PERSON_TYPES = frozenset(
    {"BD", "BK", "CP", "CO", "EP", "FI", "HC", "IA", "IC", "IN", "IV", "PN", "SA", "OO"}
)
SCHEDULE_13G_BUSINESS_ENGAGED_TYPES = frozenset(
    {"BD", "BK", "CP", "EP", "FI", "HC", "IA", "IC", "IV", "SA", "OO"}
)

SCHEDULE_13D_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition("ITEM 1", 1, ("security and issuer", "security", "issuer")),
    ItemDefinition("ITEM 2", 1, ("identity and background", "identity", "background")),
    ItemDefinition(
        "ITEM 3",
        1,
        (
            "source and amount of funds or other consideration",
            "source and amount of funds",
        ),
    ),
    ItemDefinition("ITEM 4", 1, ("purpose of transaction",)),
    ItemDefinition(
        "ITEM 5",
        1,
        ("interest in securities of the issuer", "interest in securities"),
    ),
    ItemDefinition(
        "ITEM 6",
        1,
        (
            "contracts, arrangements, understandings or relationships with respect to securities of the issuer",
            "contracts, arrangements, understandings or relationships with respect to securities",
        ),
    ),
    ItemDefinition("ITEM 7", 1, ("material to be filed as exhibits", "exhibits")),
)

SCHEDULE_13G_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition("ITEM 1", 1, ("issuer information", "name of issuer", "issuer")),
    ItemDefinition(
        "ITEM 2",
        1,
        ("filer information", "name of person filing", "person filing", "identity"),
    ),
    ItemDefinition(
        "ITEM 3",
        1,
        (
            "if this statement is filed pursuant to",
            "type of reporting person",
            "rule 13d-1(b)",
            "rule 13d-1(c)",
        ),
    ),
    ItemDefinition("ITEM 4", 1, ("ownership", "amount beneficially owned")),
    ItemDefinition(
        "ITEM 5",
        1,
        ("ownership of five percent or less of a class", "ownership of 5% or less"),
    ),
    ItemDefinition(
        "ITEM 6",
        1,
        (
            "ownership of more than five percent on behalf of another person",
            "ownership of more than 5% on behalf of another",
        ),
    ),
    ItemDefinition(
        "ITEM 7",
        1,
        (
            "identification and classification of the subsidiary which acquired the security being reported on by the parent holding company or control person",
            "identification and classification of the subsidiary",
            "subsidiary",
        ),
    ),
    ItemDefinition(
        "ITEM 8",
        1,
        (
            "identification and classification of members of the group",
            "identification and classification of members",
            "members of the group",
        ),
    ),
    ItemDefinition(
        "ITEM 9",
        1,
        ("notice of dissolution of group", "dissolution of group"),
    ),
    ItemDefinition(
        "ITEM 10",
        1,
        ("certifications", "certification"),
    ),
)

__all__ = [
    "SCHEDULE_13D_FUND_TYPES",
    "SCHEDULE_13D_ITEMS",
    "SCHEDULE_13D_MEMBER_TYPES",
    "SCHEDULE_13D_REPORTING_PERSON_TYPES",
    "SCHEDULE_13D_SUBMISSION_TYPES",
    "SCHEDULE_13G_BUSINESS_ENGAGED_TYPES",
    "SCHEDULE_13G_GROUP_TYPES",
    "SCHEDULE_13G_ITEMS",
    "SCHEDULE_13G_REPORTING_PERSON_TYPES",
    "SCHEDULE_13G_RULE_TYPES",
    "SCHEDULE_13G_SUBMISSION_TYPES",
    "SCHEDULE_LIVE_TEST_TYPES",
]
