from __future__ import annotations

from edgar_sec.domain.forms.families.beneficial_ownership.taxonomy import (
    SCHEDULE_13D_FUND_TYPES,
    SCHEDULE_13D_ITEMS,
    SCHEDULE_13D_REPORTING_PERSON_TYPES,
    SCHEDULE_13D_SUBMISSION_TYPES,
    SCHEDULE_13G_BUSINESS_ENGAGED_TYPES,
    SCHEDULE_13G_GROUP_TYPES,
    SCHEDULE_13G_ITEMS,
    SCHEDULE_13G_REPORTING_PERSON_TYPES,
    SCHEDULE_13G_RULE_TYPES,
    SCHEDULE_13G_SUBMISSION_TYPES,
    SCHEDULE_LIVE_TEST_TYPES,
)
from edgar_sec.domain.taxonomy.jurisdictions import EDGAR_JURISDICTION_CODES


def test_schedule_13d_taxonomy_covers_items_one_through_seven() -> None:
    assert tuple(item.item for item in SCHEDULE_13D_ITEMS) == tuple(
        f"ITEM {i}" for i in range(1, 8)
    )


def test_schedule_13g_taxonomy_covers_items_one_through_ten() -> None:
    assert tuple(item.item for item in SCHEDULE_13G_ITEMS) == tuple(
        f"ITEM {i}" for i in range(1, 11)
    )


def test_schedule_xml_code_sets_match_the_documented_choices() -> None:
    assert SCHEDULE_13D_SUBMISSION_TYPES == {"SCHEDULE 13D", "SCHEDULE 13D/A"}
    assert SCHEDULE_13G_SUBMISSION_TYPES == {"SCHEDULE 13G", "SCHEDULE 13G/A"}
    assert SCHEDULE_LIVE_TEST_TYPES == {"LIVE", "TEST"}
    assert SCHEDULE_13D_FUND_TYPES == {"SC", "BK", "AF", "WC", "PF", "OO"}
    assert SCHEDULE_13D_REPORTING_PERSON_TYPES == {
        "BD",
        "BK",
        "CP",
        "CO",
        "EP",
        "IN",
        "IA",
        "IC",
        "IV",
        "HC",
        "PN",
        "SA",
        "OO",
    }
    assert SCHEDULE_13G_RULE_TYPES == {
        "Rule 13d-1(b)",
        "Rule 13d-1(c)",
        "Rule 13d-1(d)",
    }
    assert SCHEDULE_13G_GROUP_TYPES == {"a", "b"}
    assert "FI" in SCHEDULE_13G_REPORTING_PERSON_TYPES
    assert "FI" not in SCHEDULE_13D_REPORTING_PERSON_TYPES
    assert SCHEDULE_13G_BUSINESS_ENGAGED_TYPES == {
        "BD",
        "BK",
        "CP",
        "EP",
        "FI",
        "HC",
        "IA",
        "IC",
        "IV",
        "SA",
        "OO",
    }
    assert EDGAR_JURISDICTION_CODES
