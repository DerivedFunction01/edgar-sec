"""Precision veto pass: the round-2 packet tests (labor
contributions placement, DT-S3X relief), split from
test_precision_veto_evidence.py at the file-length cap.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    ClaimEvidence,
    ClaimGroup,
    CompetitionResult,
    FamilyScore,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.vetoes.ppe_veto_evidence import ClaimStage
from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    TEST_COMPOSITION_TWIN,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_types import (
    FormTestOutcome,
)
from edgar_sec.engine.tables.extraction.vetoes.precision_veto_evidence import (
    apply_precision_vetoes,
)
from tests.engine.tables.extraction.vetoes.test_precision_veto_evidence import (
    _dt_details,
    _labor_details,
    _result,
)


def test_contributions_caption_without_expiration_fires():
    geo = GeometryText(headers=("Contributions of Matson",))
    results = apply_precision_vetoes([geo], [_result(("labor_contracts",))])
    assert "labor_contracts" not in results[0].claims
    assert _labor_details(results[0]) == [
        "precision veto: hdr:contributions-no-expiration"
    ]


def test_contributions_with_in_geometry_expiration_keeps_the_claim():
    geo = GeometryText(
        headers=(
            "Contributions of Safeway (in millions)",
            "Surcharge imposed (1)",
            "Expiration date of collective bargaining agreements",
            "Total collective bargaining agreements",
        )
    )
    results = apply_precision_vetoes([geo], [_result(("labor_contracts",))])
    assert "labor_contracts" in results[0].claims
    assert _labor_details(results[0]) == []


def test_contributions_with_cba_expiration_header_keeps_the_claim():
    geo = GeometryText(
        headers=(
            "Contributions of the Company",
            "Collective Bargaining Agreement Expiration Date",
        )
    )
    results = apply_precision_vetoes([geo], [_result(("labor_contracts",))])
    assert "labor_contracts" in results[0].claims
    assert _labor_details(results[0]) == []


def test_expiration_without_contributions_keeps_the_claim():
    geo = GeometryText(
        headers=("Facility Location", "Union", "Expiration Date", "Employees Covered")
    )
    results = apply_precision_vetoes([geo], [_result(("labor_contracts",))])
    assert "labor_contracts" in results[0].claims
    assert _labor_details(results[0]) == []


def test_contributions_leg_is_family_scoped():
    geo = GeometryText(headers=("Contributions of Matson",))
    results = apply_precision_vetoes([geo], [_result(("pension",))])
    assert "pension" in results[0].claims


def test_both_labor_legs_report_in_order():
    geo = GeometryText(headers=("EIN/Plan number", "Contributions of Matson"))
    results = apply_precision_vetoes([geo], [_result(("labor_contracts",))])
    assert "labor_contracts" not in results[0].claims
    assert _labor_details(results[0]) == [
        "precision veto: hdr:employer-form, hdr:contributions-no-expiration"
    ]


_S3X_STUBS = (
    "Deferred income tax assets:",
    "Net operating loss carryforward",
    "Stock compensation",
    "Income taxes payable",
    "Less: valuation allowance",
    "Net deferred income tax assets",
)


def test_dt_s3x_relief_seats_a_dialect_composition():
    geo = GeometryText(
        stubs=_S3X_STUBS,
        lead="The components of deferred income tax assets are as follows",
        grid_text="diluted shares outstanding",
    )
    results = apply_precision_vetoes([geo], [_result(("deferred_tax",))])
    assert "deferred_tax" in results[0].claims
    assert _dt_details(results[0]) == []


def test_dt_s3x_relief_via_the_composition_form_test():
    geo = GeometryText(
        stubs=(
            "Deferred income tax assets:",
            "Net operating loss carryforward",
            "Stock compensation",
            "Income taxes payable",
        ),
        lead_title="Deferred income taxes",
        grid_text="diluted shares outstanding",
        form_tests=(
            FormTestOutcome(
                "deferred_tax",
                "deferred_tax_composition",
                "composition",
                True,
                True,
                0,
                3.0,
                "passed",
            ),
        ),
    )
    results = apply_precision_vetoes([geo], [_result(("deferred_tax",))])
    assert "deferred_tax" in results[0].claims
    assert _dt_details(results[0]) == []


def test_dt_s3x_no_relief_without_lead_subject():
    geo = GeometryText(
        stubs=_S3X_STUBS,
        grid_text="diluted shares outstanding",
    )
    results = apply_precision_vetoes([geo], [_result(("deferred_tax",))])
    assert "deferred_tax" not in results[0].claims
    assert _dt_details(results[0]) == [
        "precision veto: bigram:income taxes, form:no-dt-subject"
    ]


def test_dt_s3x_relief_stops_at_other_legs():
    geo = GeometryText(
        stubs=_S3X_STUBS,
        lead="The components of deferred income tax assets are as follows",
        grid_text="diluted shares outstanding",
        pct_row_share=0.5,
    )
    results = apply_precision_vetoes([geo], [_result(("deferred_tax",))])
    assert "deferred_tax" not in results[0].claims
    assert _dt_details(results[0]) == [
        "precision veto: pct-rows, bigram:income taxes, form:no-dt-subject"
    ]


def test_dt_s3x_no_relief_for_the_schedule_ii_specimen_shape():
    geo = GeometryText(
        stubs=(
            "Reserves and allowances deducted from asset accounts:",
            "Valuation allowance for deferred tax assets",
            "Reserves for non-income taxes",
        ),
        grid_text="diluted shares outstanding",
    )
    results = apply_precision_vetoes([geo], [_result(("deferred_tax",))])
    assert "deferred_tax" not in results[0].claims
    assert _dt_details(results[0]) == ["precision veto: bigram:income taxes"]


def test_dt_s3x_relief_stops_at_the_schedule_ii_form():
    geo = GeometryText(
        stubs=_S3X_STUBS,
        headers=("Reserves and allowances deducted from assets",),
        lead="The components of deferred income tax assets are as follows",
        grid_text="diluted shares outstanding",
    )
    results = apply_precision_vetoes([geo], [_result(("deferred_tax",))])
    assert "deferred_tax" not in results[0].claims
    assert "form:schedule-ii" in _dt_details(results[0])[0]


def test_dt_s3x_no_relief_for_a_reconciliation_with_a_va_line():
    geo = GeometryText(
        stubs=(
            "Net income (loss) before income taxes",
            "Tax expenses (benefit) at the statutory tax rate",
            "Permanent differences",
            "Other adjustments",
            "Valuation allowance",
            "Income tax benefit",
        ),
        lead="The deferred tax reconciliation is as follows",
        grid_text="diluted shares outstanding",
    )
    results = apply_precision_vetoes([geo], [_result(("deferred_tax",))])
    assert "deferred_tax" not in results[0].claims
    assert _dt_details(results[0]) == [
        "precision veto: bigram:income taxes, form:no-dt-subject"
    ]
