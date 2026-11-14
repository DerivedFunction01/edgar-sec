"""Profile registry: the supported set and its Step 6 support states."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.profiles import (
    FORM_TESTS,
    KIND_GENRE_SEAT,
    PROFILES,
    PROFILES_BY_FAMILY,
    RETIRED_FAMILY_NAMES,
    TEST_COMPOSITION_TWIN,
    TEST_LADDER,
    TEST_PERCENTAGE_FORM,
    TEST_PRIMARY_STATEMENT_SEAT,
    TEST_WALK,
    competing_families,
    is_retired,
    profile_for,
)

OPEN_FAMILIES = {
    "aoci_rollforward",
    "balance_sheet",
    "cash_flow",
    "commitments_contingencies",
    "comprehensive_income",
    "debt_maturity",
    "deferred_tax",
    "derivatives_hedging",
    "eps_reconciliation",
    "equity_statement",
    "fair_value",
    "income_statement",
    "intangibles",
    "inventory",
    "lease_maturity",
    "pension",
    "ppe",
    "related_party",
    "segment_reporting",
    "stock_comp_rollforward",
    "tax_reconciliation",
}
STATEMENT_FAMILIES = {
    "balance_sheet",
    "cash_flow",
    "comprehensive_income",
    "equity_statement",
    "income_statement",
}


def test_registry_covers_exactly_the_supported_set() -> None:
    families = {profile.family for profile in PROFILES}
    assert OPEN_FAMILIES <= families
    assert families == OPEN_FAMILIES | {
        "labor_capture",
        "demographics",
        "cover_layout",
        "shares_purchased",
        "other",
    }
    assert len(PROFILES) == len(PROFILES_BY_FAMILY)


def test_subsequent_events_is_retired_data_and_cannot_claim() -> None:
    assert is_retired("subsequent_events")
    assert RETIRED_FAMILY_NAMES == {"subsequent_events"}
    assert profile_for("subsequent_events") is None
    assert "subsequent_events" not in PROFILES_BY_FAMILY
    assert "subsequent_events" not in competing_families()
    assert all(profile.family != "subsequent_events" for profile in PROFILES)


def test_no_profile_no_claims_for_unknown_families() -> None:
    assert profile_for("no_such_family") is None
    assert set(competing_families()) == OPEN_FAMILIES | {
        "labor_capture",
        "demographics",
    }


def test_every_profile_reads_no_prose_window() -> None:
    assert all(profile.prose_window == "none" for profile in PROFILES)


def test_support_states_are_the_step6_readings() -> None:
    deriv = PROFILES_BY_FAMILY["derivatives_hedging"].support
    assert deriv is not None
    assert (deriv.annual_precision, deriv.annual_recall) == (0.691, 0.786)
    assert (deriv.quarterly_precision, deriv.quarterly_recall) == (0.714, 0.826)
    aoci = PROFILES_BY_FAMILY["aoci_rollforward"].support
    assert aoci is not None
    assert aoci.assembly_quarterly_precision == 0.083
    deferred = PROFILES_BY_FAMILY["deferred_tax"].support
    assert deferred is not None
    assert deferred.quarterly_recall is None
    assert deferred.quarterly_directed_recall == 0.942
    tax = PROFILES_BY_FAMILY["tax_reconciliation"].support
    assert tax is not None
    assert tax.quarterly_recall is None
    assert tax.quarterly_directed_recall == 0.758
    assert all(
        profile.support is not None
        for profile in PROFILES
        if profile.family in OPEN_FAMILIES
    )


def test_exhibit_links_are_ex13_annual_only_on_statement_families() -> None:
    linked = {
        profile.family
        for profile in PROFILES
        if any(link.exhibit_type == "EX-13" for link in profile.exhibit_links)
    }
    assert linked == STATEMENT_FAMILIES
    for profile in PROFILES:
        for link in profile.exhibit_links:
            assert link.strata == ("B",)
    assert all(
        link.exhibit_type != "EX-99"
        for profile in PROFILES
        for link in profile.exhibit_links
    )


def test_form_test_declarations_are_named_data() -> None:
    for profile in PROFILES:
        assert all(test in FORM_TESTS for test in profile.form_tests)
    assert TEST_WALK in PROFILES_BY_FAMILY["aoci_rollforward"].form_tests
    assert TEST_WALK in PROFILES_BY_FAMILY["stock_comp_rollforward"].form_tests
    assert TEST_LADDER in PROFILES_BY_FAMILY["debt_maturity"].form_tests
    assert TEST_LADDER in PROFILES_BY_FAMILY["commitments_contingencies"].form_tests
    assert TEST_PERCENTAGE_FORM in PROFILES_BY_FAMILY["tax_reconciliation"].form_tests
    for family in STATEMENT_FAMILIES - {"comprehensive_income"}:
        assert TEST_PRIMARY_STATEMENT_SEAT in PROFILES_BY_FAMILY[family].form_tests
    for family in ("pension", "ppe", "intangibles", "inventory", "fair_value"):
        assert TEST_COMPOSITION_TWIN in PROFILES_BY_FAMILY[family].form_tests


def test_admitted_and_genre_profiles() -> None:
    demo = PROFILES_BY_FAMILY["demographics"]
    assert demo.region_gate is not None and "Item 1" in demo.region_gate
    assert demo.shape is not None and "no currency" in demo.shape
    labor = PROFILES_BY_FAMILY["labor_capture"]
    assert labor.kind == "prose_profile"
    assert labor.shape == "employee group x contract x union"
    genre = [p for p in PROFILES if p.kind == KIND_GENRE_SEAT]
    assert {p.family for p in genre} == {"cover_layout", "shares_purchased", "other"}
    assert all(p.support is None and not p.form_tests for p in genre)
