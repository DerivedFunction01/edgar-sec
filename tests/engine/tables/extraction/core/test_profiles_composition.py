"""Composition-twin specs: registry shape and specimen semantics.

Specimens are transcribed from the Step 6 adjudicated directed
records named in each spec's provenance.
"""

from __future__ import annotations

from edgar_sec.foundation.text.date_patterns import YEAR_TOKEN_SEARCH_RE
from edgar_sec.engine.tables.extraction.form_specs.composition_specs import (
    COMPOSITION_SPECS,
    COMPOSITION_SPECS_BY_FAMILY,
    CompositionSpec,
    composition_spec_for,
)
from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    TEST_COMPOSITION_TWIN,
)
from edgar_sec.engine.tables.extraction.core.subjects.profiles import (
    PROFILES,
)

TWIN_FAMILIES = {
    "pension",
    "ppe",
    "intangibles",
    "deferred_tax",
    "inventory",
    "lease_maturity",
    "fair_value",
}

Row = tuple[str, tuple[str, ...]]


def _amount_bearing(cells: tuple[str, ...]) -> bool:
    return any(any(ch.isdigit() for ch in cell) and "%" not in cell for cell in cells)


def _is_total(spec: CompositionSpec, stub: str) -> bool:
    return any(term in stub for term in spec.total_terms)


def _class_rows(spec: CompositionSpec, rows: tuple[Row, ...]) -> tuple[Row, ...]:
    return tuple(
        (stub, cells)
        for stub, cells in rows
        if _amount_bearing(cells) and not _is_total(spec, stub.lower())
    )


def _group_hits(spec: CompositionSpec, texts: tuple[str, ...]) -> int:
    return sum(
        1
        for group in spec.stub_groups
        if any(term in text for term in group for text in texts)
    )


def passes(spec: CompositionSpec, header: str, rows: tuple[Row, ...]) -> bool:
    """The spec's declared reading, applied to one specimen table."""
    class_rows = _class_rows(spec, rows)
    if len(class_rows) < spec.min_class_rows:
        return False
    if spec.orientation == "columns":
        return _group_hits(spec, (header.lower(),)) >= spec.min_stub_groups
    stubs = tuple(stub.lower() for stub, _ in class_rows)
    if _group_hits(spec, stubs) < spec.min_stub_groups:
        return False
    anywhere = " ".join((header.lower(), *stubs))
    column_hits = sum(
        1 for group in spec.column_groups if any(term in anywhere for term in group)
    )
    if column_hits >= spec.min_column_groups:
        return True
    years = set(YEAR_TOKEN_SEARCH_RE.findall(header))
    return spec.period_columns and len(years) >= 2


def test_specs_cover_exactly_the_composition_twin_families() -> None:
    assert {spec.family for spec in COMPOSITION_SPECS} == TWIN_FAMILIES
    assert len(COMPOSITION_SPECS) == len(COMPOSITION_SPECS_BY_FAMILY)
    declared = {
        profile.family
        for profile in PROFILES
        if TEST_COMPOSITION_TWIN in profile.form_tests
    }
    assert declared == TWIN_FAMILIES
    for family in TWIN_FAMILIES:
        assert composition_spec_for(family) is not None
    assert composition_spec_for("debt_maturity") is None


def test_every_spec_is_a_real_composition_test() -> None:
    for spec in COMPOSITION_SPECS:
        assert spec.min_stub_groups >= 1
        assert spec.min_class_rows >= 2
        assert spec.stub_groups and all(spec.stub_groups)
        assert "totals_only" in spec.refused_shapes or spec.family in {
            "deferred_tax",
            "lease_maturity",
        }
        assert "single_line_summary" in spec.refused_shapes or (
            "single_class_summary" in spec.refused_shapes
        )
        class_terms = {term for group in spec.stub_groups for term in group}
        assert not class_terms & set(spec.total_terms)


def test_pension_passes_cost_components_and_fails_lookalikes() -> None:
    spec = composition_spec_for("pension")
    assert spec is not None
    components = (
        ("Service cost", ("$ 12,400",)),
        ("Interest cost", ("9,850",)),
        ("Expected return on plan assets", ("(11,200)",)),
        ("Amortization of prior service cost", ("310",)),
        ("Net periodic benefit cost", ("$ 11,360",)),
    )
    assert passes(spec, "Three Months Ended March 31", components)
    aoci_summary = (("Pension and postretirement plans, net of tax", ("(4,120)",)),)
    assert not passes(spec, "Other comprehensive income", aoci_summary)
    assumptions = (
        ("Discount rate", ("5.25 %",)),
        ("Expected return on plan assets", ("6.50 %",)),
        ("Rate of compensation increase", ("3.00 %",)),
    )
    assert not passes(spec, "Weighted-average assumptions", assumptions)


def test_ppe_passes_class_composition_and_fails_totals_only() -> None:
    spec = composition_spec_for("ppe")
    assert spec is not None
    composition = (
        ("Land", ("$ 18,200",)),
        ("Buildings and improvements", ("96,400",)),
        ("Machinery and equipment", ("210,750",)),
        ("Transportation equipment", ("12,300",)),
        ("Construction in process", ("8,900",)),
        ("Less accumulated depreciation", ("(140,600)",)),
        ("Property and equipment, net", ("$ 205,950",)),
    )
    assert passes(spec, "December 31, 2024 December 31, 2023", composition)
    totals_only = (("Property and equipment, net", ("$ 205,950",)),)
    assert not passes(spec, "December 31, 2024", totals_only)


def test_intangibles_wd40_totals_only_fails_charles_river_passes() -> None:
    spec = composition_spec_for("intangibles")
    assert spec is not None
    header = "Gross Carrying Amount Accumulated Amortization Net Carrying Amount"
    wd40_totals_only = (
        ("Gross carrying amount", ("$ 48,900",)),
        ("Accumulated amortization", ("(21,300)",)),
        ("Net carrying amount", ("$ 27,600",)),
    )
    assert not passes(spec, header, wd40_totals_only)
    charles_river = (
        ("Backlog", ("$ 62,000", " (9,100)", " $ 52,900")),
        ("Technology", ("148,500", " (61,400)", " 87,100")),
        ("Trademarks and trade names", ("39,200", " (12,800)", " 26,400")),
    )
    assert passes(spec, header, charles_river)
    allocation = (
        ("Technology", ("$ 148,500", " 7.5 years")),
        ("Customer relationships", ("96,000", " 12.0 years")),
        ("Backlog", ("62,000", " 1.5 years")),
    )
    assert not passes(spec, "Fair Value Weighted-Average Life", allocation)
    ladder = (
        ("Customer relationships", ("$ 8,400", " $ 8,400", " $ 8,100")),
        ("Patents", ("1,900", " 1,900", " 1,700")),
    )
    assert passes(spec, "2025 2026 2027", ladder)


def test_deferred_tax_passes_dta_dtl_composition_and_fails_walk() -> None:
    spec = composition_spec_for("deferred_tax")
    assert spec is not None
    crona = (
        ("Net operating loss carry forward", ("$ (9,064)",)),
        ("Valuation allowance", ("9,064",)),
        ("Net deferred tax assets", ("$ -",)),
    )
    assert passes(spec, "As of March 31, 2020 As of December 31, 2019", crona)
    allowance_walk = (
        ("Balance at beginning of period", ("$ 8,581",)),
        ("Additions charged to expense", ("483",)),
        ("Balance at end of period", ("$ 9,064",)),
    )
    assert not passes(spec, "Valuation allowance", allowance_walk)
    single_line = (("Deferred tax assets, net", ("$ 4,200",)),)
    assert not passes(spec, "December 31, 2024", single_line)


def test_inventory_passes_class_composition_and_fails_single_line() -> None:
    spec = composition_spec_for("inventory")
    assert spec is not None
    composition = (
        ("Raw materials", ("$ 84,100",)),
        ("Work in process", ("39,650",)),
        ("Finished goods", ("112,480",)),
        ("Total inventories", ("$ 236,230",)),
    )
    assert passes(spec, "December 31, 2024 December 31, 2023", composition)
    single_line = (("Inventories, net", ("$ 236,230",)),)
    assert not passes(spec, "December 31, 2024", single_line)


def test_lease_maturity_passes_class_ladder_and_fails_cost_only() -> None:
    spec = composition_spec_for("lease_maturity")
    assert spec is not None
    ladder = (
        ("2026", ("$ 14,200", " $ 6,100")),
        ("2027", ("13,800", " 5,900")),
        ("2028", ("12,450", " 5,200")),
        ("Thereafter", ("31,700", " 18,300")),
        ("Total undiscounted lease payments", ("$ 84,550", " $ 41,600")),
        ("Less imputed interest", ("(9,300)", " (4,800)")),
        ("Total lease liabilities", ("$ 75,250", " $ 36,800")),
    )
    assert passes(spec, "Operating Leases Finance Leases", ladder)
    cost_only = (
        ("Operating lease cost", ("$ 15,100",)),
        ("Short-term lease cost", ("1,250",)),
        ("Total lease cost", ("$ 16,350",)),
    )
    assert not passes(spec, "Three Months Ended March 31", cost_only)


def test_fair_value_passes_level_composition_and_fails_nav_only() -> None:
    spec = composition_spec_for("fair_value")
    assert spec is not None
    hierarchy = (
        ("Cash equivalents", ("$ 210,400", " $ -", " $ -")),
        ("Marketable securities", ("85,200", " 412,600", " -")),
        ("Derivative assets", ("-", " 18,900", " 6,400")),
    )
    assert passes(spec, "Level 1 Level 2 Level 3", hierarchy)
    nav_portfolio = (
        ("Global equity fund", ("$ 96,000",)),
        ("Fixed income fund", ("54,300",)),
        ("Real assets fund", ("21,800",)),
    )
    assert not passes(spec, "December 31, 2024", nav_portfolio)
    single_line = (("Investments at fair value", ("$ 640,100",)),)
    assert not passes(spec, "Level 1 Level 2 Level 3", single_line)
