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
    SignatureTerm("lease_maturity", "caption", "operating lease", 2.5, 40, 2),
    SignatureTerm("lease_maturity", "leadin", "lease liabilities", 2.5, 35, 1),
    SignatureTerm("lease_maturity", "stub", "undiscounted lease payments", 2.5, 30, 0),
    SignatureTerm("debt_maturity", "caption", "long-term debt", 2.5, 40, 2),
    SignatureTerm("debt_maturity", "leadin", "senior notes", 2.5, 30, 1),
    SignatureTerm("debt_maturity", "stub", "aggregate maturities", 2.5, 25, 0),
    SignatureTerm("cash_flow", "stub", "cash flows", 0.4, 90, 80),
    SignatureTerm("equity_statement", "caption", "changes in equity", 2.5, 40, 1),
    SignatureTerm("equity_statement", "leadin", "statement of changes", 2.5, 38, 1),
    SignatureTerm("equity_statement", "notehead", "changes in equity", 2.5, 40, 2),
    SignatureTerm("equity_statement", "stub", "shares issued", 2.0, 30, 5),
    SignatureTerm("lease_maturity", "notehead", "leases", 2.5, 33, 1),
    SignatureTerm(
        "aoci_rollforward", "stub", "accumulated other comprehensive", 2.5, 30, 3
    ),
)

_EDGES = (
    ContainmentEdge("aoci_rollforward", "equity_statement", 0.75, "test census"),
    ContainmentEdge("equity_statement", "aoci_rollforward", 0.50, "test census"),
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


def test_profile_is_assembled_from_the_subject_evidence_map() -> None:
    from edgar_sec.engine.tables.extraction.signature_profiles import (
        CHANNEL_WEIGHTS,
        INHERITANCE_FACTORS,
        PROV_STEP1B_MAP,
        SIGNATURE_TERMS,
    )

    assert len(SIGNATURE_TERMS) > 3000
    assert {t.provenance for t in SIGNATURE_TERMS} == {PROV_STEP1B_MAP}
    assert {t.channel for t in SIGNATURE_TERMS} <= {
        "caption",
        "leadin",
        "notehead",
        "lead_title",
        "stub",
    }
    assert CHANNEL_WEIGHTS["lead_title"] == CHANNEL_WEIGHTS["leadin"]
    assert INHERITANCE_FACTORS["equity_statement"] > 0.6


def test_lead_title_channel_decides_an_equity_fragment() -> None:
    terms = (
        SignatureTerm(
            "equity_statement", "lead_title", "stockholders' equity", 3.0, 38, 4
        ),
        SignatureTerm(
            "equity_statement", "leadin", "statements of stockholders", 2.0, 36, 3
        ),
        SignatureTerm("equity_statement", "stub", "shares issued", 1.5, 30, 5),
        SignatureTerm("cash_flow", "stub", "cash flows", 0.4, 90, 80),
    )
    geometry = GeometryText(
        leadin="Consolidated statements of stockholders' equity (unaudited)",
        lead_title="Consolidated statements of stockholders' equity",
        stubs=("Common stock", "Shares issued"),
    )
    result = compete(geometry, terms=terms, edges=())
    assert result.claims == ("equity_statement",)
    assert "lead_title" in result.scores["equity_statement"].by_channel


def test_fragment_inherits_from_preceding_claim_in_same_note() -> None:
    # The family's inheritance factor is the map's measured
    # title-decides share; equity's is the corpus's highest, so the
    # inheritance path is exercised on an equity fragment.
    first = GeometryText(
        caption="Statements of Changes in Equity",
        leadin="Statement of changes in equity for the year.",
        notehead="Changes in Equity",
        stubs=("Shares issued", "Accumulated other comprehensive income"),
        note_title="Equity",
    )
    fragment = GeometryText(
        stubs=("Shares issued", "Dividends declared"),
        note_title="Equity",
    )
    results = compete_filing([first, fragment], terms=_TERMS, edges=_EDGES)
    assert results[0].claims == ("equity_statement",)
    assert results[1].claims == ("equity_statement",)
    channels = results[1].scores["equity_statement"].by_channel
    assert "context" in channels
