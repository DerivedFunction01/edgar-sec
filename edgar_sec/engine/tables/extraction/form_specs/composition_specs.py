"""Composition-twin specs, one per declaring family."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core.subjects.profiles import (
    PROV_FAMILY_SUPPORT,
)


@dataclass(frozen=True, slots=True)
class CompositionSpec:
    """One family's composition-twin test, declared as data.

    Passes a table enumerating the family's component classes
    with amounts per class; fails totals-only summaries.
    """

    family: str
    stub_groups: tuple[tuple[str, ...], ...]
    min_stub_groups: int
    min_class_rows: int
    column_groups: tuple[tuple[str, ...], ...] = ()
    min_column_groups: int = 0
    orientation: str = "rows"
    period_columns: bool = False
    total_terms: tuple[str, ...] = ()
    refused_shapes: tuple[str, ...] = ()
    provenance: str = PROV_FAMILY_SUPPORT


# Composition-twin specs (class (v)): one per family
# declaring TEST_COMPOSITION_TWIN, pinned from the directed
# sets and adjudicated specimens named in each provenance.
COMPOSITION_SPECS: tuple[CompositionSpec, ...] = (
    CompositionSpec(
        "pension",
        stub_groups=(
            ("service cost",),
            ("interest cost",),
            ("expected return on plan assets", "expected return"),
            ("amortization", "prior service"),
        ),
        min_stub_groups=3,
        min_class_rows=3,
        total_terms=("net periodic benefit cost", "net periodic pension cost"),
        refused_shapes=(
            "aoci_component_composition",
            "assumption_only",
            "single_line_summary",
            "totals_only",
        ),
        provenance="directed:t5x-pension-q",
    ),
    CompositionSpec(
        "ppe",
        stub_groups=(
            ("land",),
            ("building",),
            ("machinery",),
            ("transportation", "vehicle"),
            ("construction in progress", "construction in process"),
            ("furniture", "fixture"),
            ("leasehold",),
            ("computer",),
        ),
        min_stub_groups=3,
        min_class_rows=3,
        column_groups=(
            ("accumulated depreciation",),
            ("cost", "gross"),
            ("net",),
        ),
        min_column_groups=1,
        total_terms=("total property", "property and equipment, net"),
        refused_shapes=("totals_only", "single_line_summary", "movement_only"),
        provenance="directed:t5x-ppe",
    ),
    CompositionSpec(
        "intangibles",
        stub_groups=(
            ("backlog",),
            ("technology",),
            ("trademark", "trade name", "brand"),
            ("customer",),
            ("patent",),
            ("license", "licence"),
            ("noncompete", "non-compete", "covenant"),
            ("franchise",),
            ("supplier",),
        ),
        min_stub_groups=2,
        min_class_rows=2,
        column_groups=(
            ("gross carrying", "gross"),
            ("accumulated amortization",),
            ("net carrying", "net"),
        ),
        min_column_groups=2,
        period_columns=True,
        total_terms=("total intangible",),
        refused_shapes=(
            "totals_only",
            "purchase_price_allocation",
            "rollforward_by_category",
            "single_class_summary",
        ),
        provenance="directed:t5x-intangibles-q",
    ),
    CompositionSpec(
        "deferred_tax",
        stub_groups=(
            ("net operating loss", "loss carryforward"),
            ("tax credit", "credit carryforward"),
            ("capital loss",),
            ("accrued",),
            ("stock compensation", "share-based compensation"),
            ("valuation allowance",),
            ("depreciation",),
            ("amortization",),
            ("right-of-use", "right of use"),
            ("unrealized",),
            ("prepaid",),
        ),
        min_stub_groups=2,
        min_class_rows=2,
        total_terms=("net deferred tax", "total deferred"),
        refused_shapes=(
            "allowance_walk_only",
            "provision_detail",
            "single_line_summary",
        ),
        provenance="directed:t3-deferred_tax",
    ),
    CompositionSpec(
        "inventory",
        stub_groups=(
            ("raw material",),
            ("work in process", "work-in-process", "work in progress"),
            ("finished good",),
            ("supplies",),
            ("merchandise",),
        ),
        min_stub_groups=2,
        min_class_rows=2,
        total_terms=("total inventories", "total inventory", "inventories, net"),
        refused_shapes=("totals_only", "single_line_summary"),
        provenance="directed:t5x-inventory-q",
    ),
    CompositionSpec(
        "lease_maturity",
        stub_groups=(
            ("operating lease",),
            ("finance lease",),
            ("capital lease",),
        ),
        min_stub_groups=1,
        min_class_rows=3,
        orientation="columns",
        total_terms=(
            "total undiscounted",
            "total lease payments",
            "imputed interest",
            "total lease liabilities",
            "present value",
        ),
        refused_shapes=(
            "cost_composition_only",
            "totals_only",
            "single_line_summary",
        ),
        provenance="directed:t5x-lease_maturity",
    ),
    CompositionSpec(
        "fair_value",
        stub_groups=(
            ("level 1",),
            ("level 2",),
            ("level 3",),
            ("net asset value", "nav"),
        ),
        min_stub_groups=2,
        min_class_rows=2,
        orientation="columns",
        total_terms=("total assets", "total liabilities"),
        refused_shapes=(
            "portfolio_composition_no_levels",
            "totals_only",
            "single_line_summary",
        ),
        provenance="directed:fair_value-levels",
    ),
)

COMPOSITION_SPECS_BY_FAMILY = {spec.family: spec for spec in COMPOSITION_SPECS}


def composition_spec_for(family: str) -> CompositionSpec | None:
    """The family's composition-twin spec, or None if it has none."""
    return COMPOSITION_SPECS_BY_FAMILY.get(family)
