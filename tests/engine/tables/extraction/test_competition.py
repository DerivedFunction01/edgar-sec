"""Signature competition: dominance, containment, inheritance."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.competition import (
    GeometryText,
    compete,
    compete_filing,
)
from edgar_sec.engine.tables.extraction.signature_profiles import (
    ContainmentEdge,
    SignatureTerm,
)

_TERMS = (
    SignatureTerm("lease_maturity", "caption", "operating lease", 2.0, 40, 2),
    SignatureTerm("lease_maturity", "leadin", "lease liabilities", 2.0, 35, 1),
    SignatureTerm("lease_maturity", "stub", "undiscounted lease payments", 2.0, 30, 0),
    SignatureTerm("debt_maturity", "caption", "long-term debt", 2.0, 40, 2),
    SignatureTerm("debt_maturity", "leadin", "senior notes", 2.0, 30, 1),
    SignatureTerm("debt_maturity", "stub", "aggregate maturities", 2.0, 25, 0),
    SignatureTerm("cash_flow", "stub", "cash flows", 0.4, 90, 80),
    SignatureTerm("equity_statement", "caption", "changes in equity", 2.0, 40, 1),
    SignatureTerm("equity_statement", "leadin", "statement of changes", 2.0, 38, 1),
    SignatureTerm("equity_statement", "stub", "shares issued", 1.5, 30, 5),
    SignatureTerm("lease_maturity", "notehead", "leases", 2.0, 33, 1),
    SignatureTerm(
        "aoci_rollforward", "stub", "accumulated other comprehensive", 2.0, 30, 3
    ),
)

_EDGES = (
    ContainmentEdge("aoci_rollforward", "equity_statement", 0.75, "test census"),
    ContainmentEdge("equity_statement", "aoci_rollforward", 0.50, "test census"),
)


def _lease_geometry() -> GeometryText:
    return GeometryText(
        caption="Operating Lease Liabilities",
        leadin="The following table presents lease liabilities by year.",
        stubs=(
            "2025",
            "2026",
            "Total undiscounted lease payments",
            "Less imputed interest",
        ),
    )


def test_dominant_profile_claims_and_single_foreign_word_does_not() -> None:
    geometry = GeometryText(
        caption="Operating Lease Liabilities",
        leadin="Lease liabilities mature as follows; future cash flows are summarized.",
        stubs=("2025", "Total undiscounted lease payments"),
    )
    result = compete(geometry, terms=_TERMS, edges=_EDGES)
    assert result.claims == ("lease_maturity",)
    assert "cash_flow" not in result.claims


def test_foreign_mass_blocks_a_weak_claim() -> None:
    geometry = GeometryText(
        caption="Long-term Debt and Operating Lease",
        leadin="Senior notes and lease liabilities are presented together.",
        stubs=("Aggregate maturities", "Total undiscounted lease payments"),
    )
    result = compete(geometry, terms=_TERMS, edges=_EDGES)
    assert len(result.claims) == 2
    assert set(result.contested) == {"debt_maturity", "lease_maturity"}


def test_below_floor_issues_no_claim() -> None:
    geometry = GeometryText(stubs=("Cash flows from operations",))
    result = compete(geometry, terms=_TERMS, edges=_EDGES)
    assert result.claims == ()


def test_containment_edge_explains_aoci_mass_inside_equity() -> None:
    geometry = GeometryText(
        caption="Statements of Changes in Equity",
        leadin="Statement of changes in equity for the year.",
        stubs=(
            "Shares issued",
            "Accumulated other comprehensive income",
            "Accumulated other comprehensive loss",
        ),
    )
    result = compete(geometry, terms=_TERMS, edges=_EDGES)
    assert "equity_statement" in result.claims
    assert result.foreign_explained.get("aoci_rollforward", 0.0) > 0.0


def test_closure_corroborates_but_never_vetoes() -> None:
    open_geometry = GeometryText(
        caption="Operating Lease Liabilities",
        leadin="Lease liabilities by year.",
        stubs=("Total undiscounted lease payments",),
        closure_closed=False,
    )
    closed_geometry = GeometryText(
        caption="Operating Lease Liabilities",
        leadin="Lease liabilities by year.",
        stubs=("Total undiscounted lease payments",),
        closure_closed=True,
    )
    assert compete(open_geometry, terms=_TERMS, edges=_EDGES).claims == (
        "lease_maturity",
    )
    assert compete(closed_geometry, terms=_TERMS, edges=_EDGES).claims == (
        "lease_maturity",
    )


def test_fragment_inherits_from_preceding_claim_in_same_note() -> None:
    first = _lease_geometry()
    fragment = GeometryText(
        stubs=("2027", "2028", "Total undiscounted lease payments"),
        note_title="Leases",
    )
    first = GeometryText(
        caption=first.caption,
        leadin=first.leadin,
        notehead="Leases",
        stubs=first.stubs,
        note_title="Leases",
    )
    results = compete_filing([first, fragment], terms=_TERMS, edges=_EDGES)
    assert results[0].claims == ("lease_maturity",)
    assert results[1].claims == ("lease_maturity",)
    channels = results[1].scores["lease_maturity"].by_channel
    assert "context" in channels
