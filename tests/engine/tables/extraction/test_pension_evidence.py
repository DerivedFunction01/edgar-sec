"""Pension core-anchor gate: leg shapes, prose completion, oci."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.competition import GeometryText
from edgar_sec.engine.tables.extraction.pension_evidence import (
    PENSION_ANCHOR_SPECS,
    PensionText,
    evaluate_pension_anchor,
    pension_anchor_set,
)

SPEC = PENSION_ANCHOR_SPECS["pension"]


def _anchors(text: PensionText) -> frozenset[str]:
    return pension_anchor_set(text, SPEC)


def test_npbc_needs_two_groups() -> None:
    full = PensionText(
        stubs=("Service cost", "Interest cost", "Expected return", "Total")
    )
    assert _anchors(full) == frozenset({"npbc"})
    partial = PensionText(stubs=("Service cost", "Interest cost", "Total"))
    assert _anchors(partial) == frozenset({"npbc"})
    single = PensionText(stubs=("Service cost", "Total"))
    assert "npbc" not in _anchors(single)


def test_walk_leg_reads_the_grid() -> None:
    text = PensionText(
        grid_text=(
            "benefit obligation at beginning of year 100 "
            "benefit obligation at end of year 110"
        )
    )
    assert _anchors(text) == frozenset({"walk"})


def test_assumptions_leg_needs_anchor_and_partner() -> None:
    text = PensionText(stubs=("Discount rate", "Expected return on assets"))
    assert _anchors(text) == frozenset({"assumptions"})
    lone = PensionText(stubs=("Discount rate", "Mortality"))
    assert "assumptions" not in _anchors(lone)


def test_payments_year_count_reads_stubs_only() -> None:
    stubs = ("2026", "2027", "2028", "2029", "Thereafter")
    text = PensionText(stubs=stubs, lead="Estimated future pension payments")
    assert _anchors(text) == frozenset({"payments"})
    prose_years = PensionText(
        stubs=("Total",), lead="pension", prose_after="2026 2027 2028 2029"
    )
    assert "payments" not in _anchors(prose_years)


def test_sensitivity_and_funded_legs() -> None:
    sens = PensionText(
        grid_text="a one percentage point change in the benefit obligation"
    )
    assert _anchors(sens) == frozenset({"sensitivity"})
    funded = PensionText(stubs=("Funded status", "Total"))
    assert _anchors(funded) == frozenset({"funded"})


def test_sensitivity_leg_reads_the_hyphenated_anchor() -> None:
    text = PensionText(
        grid_text=(
            "effect of a one-percentage-point increase on the benefit obligation"
        )
    )
    assert _anchors(text) == frozenset({"sensitivity"})


def test_contributions_leg_needs_stub_and_lead_context() -> None:
    text = PensionText(
        stubs=("U.S. defined benefit plans", "Non-U.S. defined benefit plans"),
        lead="The company expects to make contributions to its plans",
    )
    assert _anchors(text) == frozenset({"contributions"})
    stub_only = PensionText(
        stubs=("U.S. defined benefit plans",),
        lead="The following table presents amounts by geography",
    )
    assert "contributions" not in _anchors(stub_only)
    lead_only = PensionText(
        stubs=("Amounts by geography",),
        lead="Contributions to defined benefit plans are expected",
    )
    assert "contributions" not in _anchors(lead_only)


def test_allocation_needs_asset_and_lead_context() -> None:
    text = PensionText(
        stubs=("Equity securities", "Fixed income"),
        lead="The pension plan assets are invested as follows",
    )
    assert _anchors(text) == frozenset({"allocation"})
    bare = PensionText(stubs=("Equity securities", "Fixed income"))
    assert "allocation" not in _anchors(bare)


def test_oci_leg_is_a_conjunction_over_stubs() -> None:
    text = PensionText(
        stubs=(
            "Net actuarial loss",
            "Amortization of prior service credit",
            "Total recognized in other comprehensive income",
        )
    )
    assert _anchors(text) == frozenset({"oci"})
    phrase_only = PensionText(stubs=("Other comprehensive income", "Total"))
    assert "oci" not in _anchors(phrase_only)
    component_only = PensionText(stubs=("Actuarial loss", "Total"))
    assert "oci" not in _anchors(component_only)


def test_oci_leg_does_not_complete_from_prose_after() -> None:
    text = PensionText(
        stubs=("Total",),
        prose_after=("amounts in other comprehensive income include actuarial losses"),
    )
    assert "oci" not in _anchors(text)


def test_prose_after_completes_anchor_surfaces() -> None:
    stubs_only = PensionText(stubs=("Discount rate", "Mortality"))
    assert _anchors(stubs_only) == frozenset()
    completed = PensionText(
        stubs=("Discount rate", "Mortality"),
        prose_after="The expected long-term rate of return is 7 percent.",
    )
    assert _anchors(completed) == frozenset({"assumptions"})


def test_prose_after_completes_allocation_context() -> None:
    bare = PensionText(
        stubs=("Equity securities",), lead="The following table presents"
    )
    assert _anchors(bare) == frozenset()
    completed = PensionText(
        stubs=("Equity securities",),
        lead="The following table presents",
        prose_after="Assets of the pension plan are held in trust.",
    )
    assert _anchors(completed) == frozenset({"allocation"})


def test_evaluate_reports_admission_and_detail() -> None:
    admitted = evaluate_pension_anchor(PensionText(stubs=("Funded status",)), SPEC)
    assert admitted.admitted
    assert admitted.anchors == frozenset({"funded"})
    refused = evaluate_pension_anchor(PensionText(stubs=("Total",)), SPEC)
    assert not refused.admitted
    assert refused.detail == "no core anchor"


def test_from_geometry_carries_prose_after() -> None:
    geometry = GeometryText(
        stubs=("Funded status",),
        prose_after="Following prose about the plan.",
    )
    text = PensionText.from_geometry(geometry)
    assert text.stubs == ("funded status",)
    assert text.prose_after == "following prose about the plan"
