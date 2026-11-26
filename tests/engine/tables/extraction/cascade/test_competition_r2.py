"""Competition cascade: the round-2 packet tests (restructuring
charges exemption, inventory composition twin, cash_flow grantor
scoping), split from test_competition.py at the file-length cap.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.cascade.competition import compete
from edgar_sec.engine.tables.extraction.cascade.filing_competition import compete_filing
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.cascade.leadin_segmentation import (
    lead_title_text,
    leadin_segment,
)
from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    TEST_COMPOSITION_TWIN,
)
from edgar_sec.engine.tables.extraction.core.subjects.signature_profiles import (
    ContainmentEdge,
    SignatureTerm,
)
from edgar_sec.engine.tables.extraction.form_specs.form_test_types import (
    FormTestOutcome,
)
from tests.engine.tables.extraction.cascade.test_competition import (
    _CF_FULL_STUBS,
    _CF_TERMS,
    _EDGES,
    _TERMS,
)


def test_charges_claim_survives_the_summary_separator() -> None:
    from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
        ClaimEvidence,
        FamilyScore,
    )
    from edgar_sec.engine.tables.extraction.separators.summary_separator import (
        SummarySeparatorResult,
    )

    geometry = GeometryText(
        caption="Restructuring Charges",
        stubs=("Severance costs", "Facility exit costs"),
        summary_separator=SummarySeparatorResult(
            rules=("mda_item7_rows12",), sub_masses=("MD&A-SUMMARY",)
        ),
    )
    charges_score = FamilyScore(
        "restructuring",
        5.0,
        {"form_test": 3.0, "gate": 2.0},
        (
            ClaimEvidence(
                "form_test", "restructuring_rollforward_evidence passed", 3.0
            ),
            ClaimEvidence(
                "gate",
                "restructuring charges: subject prose, charges signature: "
                "cost stubs 2, numeric rows 6",
                2.0,
            ),
        ),
    )
    result = compete(
        geometry, terms=_TERMS, edges=_EDGES, scores={"restructuring": charges_score}
    )
    assert "restructuring" in result.claims
    walk_score = FamilyScore(
        "restructuring",
        5.0,
        {"form_test": 3.0, "gate": 2.0},
        (
            ClaimEvidence(
                "form_test", "restructuring_rollforward_evidence passed", 3.0
            ),
            ClaimEvidence(
                "gate",
                "restructuring walk: subject prose, bookends bare pair, movements payment",
                2.0,
            ),
        ),
    )
    result = compete(
        geometry, terms=_TERMS, edges=_EDGES, scores={"restructuring": walk_score}
    )
    assert "restructuring" not in result.claims


def _composition_outcome(family: str, passed: bool) -> FormTestOutcome:
    return FormTestOutcome(
        family=family,
        test_id=f"{family}_composition",
        kind=TEST_COMPOSITION_TWIN,
        passed=passed,
        evaluable=True,
        columns_closed=0,
        points=0.0,
        detail="",
    )


_COMPOSITION_GEOMETRY = {
    "caption": "Long-term Debt and Operating Lease",
    "leadin": "Senior notes and lease liabilities are presented together.",
    "notehead": "Leases",
    "stubs": ("Aggregate maturities", "Total undiscounted lease payments"),
}


def test_composition_failed_foreign_bars_an_uncomposed_claimant() -> None:
    geometry = GeometryText(**_COMPOSITION_GEOMETRY)
    result = compete(geometry, terms=_TERMS, edges=_EDGES)
    assert result.claims == ("lease_maturity",)


def test_composition_passed_claimant_is_not_barred_by_failed_foreign() -> None:
    geometry = GeometryText(
        **_COMPOSITION_GEOMETRY,
        form_tests=(
            _composition_outcome("debt_maturity", True),
            _composition_outcome("lease_maturity", False),
        ),
    )
    result = compete(geometry, terms=_TERMS, edges=_EDGES)
    assert "debt_maturity" in result.claims
    assert "lease_maturity" in result.claims


_CF_GRANTOR_STUBS = (
    "Cash flows from operating activities",
    "Proceeds from gold bullion sold to pay expenses",
    "Net increase in cash and cash equivalents",
    "Cash and cash equivalents, beginning of period",
)
_CF_SPINE_STUBS = (
    "Cash flows from operating activities",
    "Net cash provided by operating activities",
    "Net increase in cash and cash equivalents",
    "Cash and cash equivalents, beginning of period",
)
_CF_PER_SHARE_LEAD = (
    "The trust holds gold bullion; its net asset value per share is published daily."
)
_CF_PERIOD_GRID = "For the three months ended June 30, 2024."


def _cf_geometry(stubs, **fields) -> GeometryText:
    base = {
        "caption": "Statements of Cash Flows",
        "leadin": "The statements of cash flows are presented below.",
        "stubs": stubs,
    }
    base.update(fields)
    return GeometryText(**base)


def test_cash_flow_grantor_lead_hard_hit_scoped() -> None:
    geometry = _cf_geometry(_CF_GRANTOR_STUBS, lead=_CF_PER_SHARE_LEAD)
    assert compete(geometry, terms=_CF_TERMS, edges=()).claims == ("cash_flow",)


def test_cash_flow_grantor_body_hard_hit_scoped() -> None:
    geometry = _cf_geometry(_CF_GRANTOR_STUBS, grid_text=_CF_PERIOD_GRID)
    assert compete(geometry, terms=_CF_TERMS, edges=()).claims == ("cash_flow",)


def test_cash_flow_spine_pair_without_marker_still_bars() -> None:
    geometry = _cf_geometry(_CF_SPINE_STUBS, lead=_CF_PER_SHARE_LEAD)
    result = compete(geometry, terms=_CF_TERMS, edges=())
    assert result.claims == ()
    assert "cash_flow" in result.scores


def test_cash_flow_grantor_marker_full_presence_lead_scoped() -> None:
    stubs = _CF_FULL_STUBS + ("Proceeds from gold bullion sold to pay expenses",)
    geometry = _cf_geometry(stubs, lead=_CF_PER_SHARE_LEAD)
    assert compete(geometry, terms=_CF_TERMS, edges=()).claims == ("cash_flow",)


def test_cash_flow_grantor_marker_full_presence_body_still_bars() -> None:
    stubs = _CF_FULL_STUBS + ("Proceeds from gold bullion sold to pay expenses",)
    geometry = _cf_geometry(stubs, grid_text=_CF_PERIOD_GRID)
    assert compete(geometry, terms=_CF_TERMS, edges=()).claims == ()


def test_cash_flow_non_trust_spine_pair_body_hit_still_bars() -> None:
    grid = "Earnings per share data is omitted from this table."
    geometry = _cf_geometry(_CF_SPINE_STUBS, grid_text=grid)
    assert compete(geometry, terms=_CF_TERMS, edges=()).claims == ()
