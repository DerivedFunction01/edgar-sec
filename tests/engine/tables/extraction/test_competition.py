"""Signature competition: dominance, containment, inheritance."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.competition import (
    GeometryText,
    compete,
    compete_filing,
)
from edgar_sec.engine.tables.extraction.leadin_segmentation import (
    lead_title_text,
    leadin_segment,
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
        PROV_SUBJECT_EVIDENCE_MAP,
        SIGNATURE_TERMS,
    )

    assert len(SIGNATURE_TERMS) > 3000
    assert {t.provenance for t in SIGNATURE_TERMS} == {PROV_SUBJECT_EVIDENCE_MAP}
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


def test_groups_carry_the_scored_contract() -> None:
    geometry = GeometryText(
        caption="Operating Lease Liabilities",
        leadin="Lease liabilities mature as follows; future cash flows are summarized.",
        stubs=("2025", "Total undiscounted lease payments"),
    )
    result = compete(geometry, terms=_TERMS, edges=_EDGES)
    assert len(result.groups) == 1
    group = result.groups[0]
    assert group.family == "lease_maturity"
    assert group.state == "claimed"
    assert group.role == "head"
    assert group.veto_flags == ()
    assert group.score == result.scores["lease_maturity"].total


def test_scored_veto_can_kill_a_detail_shaped_claim() -> None:
    terms = (
        SignatureTerm("intangibles", "stub", "intangible assets", 4.0, 30, 0),
        SignatureTerm("intangibles", "caption", "intangible assets", 3.0, 30, 0),
    )
    detailed = GeometryText(
        caption="Intangible Assets",
        stubs=("Intangible assets", "2024", "2025", "Thereafter"),
    )
    plain = GeometryText(
        caption="Intangible Assets",
        stubs=("Intangible assets", "Finite-lived assets"),
    )
    killed = compete(detailed, terms=terms, edges=())
    assert killed.claims == ()
    vetoed = killed.scores["intangibles"]
    assert vetoed.by_channel["veto"] == -3.0
    flags = {e.detail for e in vetoed.evidence if e.channel == "veto"}
    assert flags == {"year_columns", "maturity_buckets"}
    assert compete(plain, terms=terms, edges=()).claims == ("intangibles",)


def test_year_columns_signature_spans_the_full_year_range() -> None:
    """Delta pin: year_columns keys on the homed year token; the
    deleted private vocabulary was hard-narrowed to 2022-2027."""
    from edgar_sec.engine.tables.extraction.competition import GeometryText
    from edgar_sec.engine.tables.extraction.detail_signatures import (
        detail_signatures,
    )

    older = GeometryText(stubs=("Revenue", "2020", "2021"))
    assert "year_columns" in detail_signatures(older)
    single = GeometryText(stubs=("Revenue", "2024"))
    assert "year_columns" not in detail_signatures(single)


def test_aoci_claim_needs_rollforward_evidence() -> None:
    terms = (
        SignatureTerm(
            "aoci_rollforward",
            "stub",
            "accumulated other comprehensive",
            4.0,
            30,
            0,
        ),
        SignatureTerm(
            "aoci_rollforward",
            "leadin",
            "accumulated other comprehensive income",
            3.0,
            30,
            0,
        ),
        SignatureTerm("equity_statement", "caption", "changes in equity", 2.5, 40, 1),
        SignatureTerm("equity_statement", "leadin", "statement of changes", 2.5, 38, 1),
        SignatureTerm("equity_statement", "stub", "shares issued", 2.0, 30, 5),
    )
    seated = GeometryText(
        caption="Statements of Changes in Equity",
        leadin=(
            "Statement of changes. Accumulated other comprehensive income is a column."
        ),
        stubs=(
            "Shares issued",
            "Accumulated other comprehensive loss",
        ),
    )
    gated = compete(seated, terms=terms, edges=_EDGES)
    assert "equity_statement" in gated.claims
    assert "aoci_rollforward" not in gated.claims
    trail = gated.scores["aoci_rollforward"].evidence
    assert any(e.channel == "gate" for e in trail)
    framed_terms = terms + (
        SignatureTerm(
            "aoci_rollforward",
            "notehead",
            "accumulated other comprehensive",
            2.5,
            30,
            0,
        ),
    )
    framed = GeometryText(
        caption="Statements of Changes in Equity",
        leadin=(
            "Statement of changes. Accumulated other comprehensive income is a column."
        ),
        notehead="Accumulated Other Comprehensive Income",
        stubs=(
            "Shares issued",
            "Accumulated other comprehensive loss",
        ),
    )
    result = compete(framed, terms=framed_terms, edges=_EDGES)
    assert "aoci_rollforward" in result.claims


def test_aoci_standalone_claim_needs_core_shape() -> None:
    terms = (
        SignatureTerm(
            "aoci_rollforward",
            "stub",
            "accumulated other comprehensive",
            4.0,
            30,
            0,
        ),
        SignatureTerm(
            "aoci_rollforward",
            "leadin",
            "accumulated other comprehensive income",
            6.0,
            30,
            0,
        ),
        SignatureTerm(
            "aoci_rollforward",
            "caption",
            "accumulated other comprehensive",
            2.5,
            30,
            0,
        ),
    )
    leadin = "The changes in accumulated other comprehensive income follow."
    walk = GeometryText(
        caption="Accumulated Other Comprehensive Income",
        leadin=leadin,
        stubs=(
            "Beginning balance",
            "Other comprehensive income before reclassifications",
            "Amounts reclassified from accumulated other comprehensive income",
            "Ending balance",
        ),
    )
    assert "aoci_rollforward" in compete(walk, terms=terms, edges=_EDGES).claims
    composition = GeometryText(
        caption="Accumulated Other Comprehensive Income",
        leadin=leadin,
        stubs=("Net actuarial gain", "Prior service cost"),
    )
    gated = compete(composition, terms=terms, edges=_EDGES)
    assert "aoci_rollforward" not in gated.claims
    assert any(
        e.channel == "gate" and "claim shape" in e.detail
        for e in gated.scores["aoci_rollforward"].evidence
    )
    generic_walk = GeometryText(
        caption="Accumulated Other Comprehensive Income",
        leadin=leadin,
        stubs=("Beginning balance", "Additions", "Ending balance"),
    )
    gated = compete(generic_walk, terms=terms, edges=_EDGES)
    assert "aoci_rollforward" not in gated.claims
    assert any(
        e.channel == "gate" and "claim shape" in e.detail
        for e in gated.scores["aoci_rollforward"].evidence
    )


def test_ladder_edge_terms_attribute_a_contested_pair() -> None:
    from edgar_sec.engine.tables.extraction.signature_profiles import LadderTerm

    ladder = (
        LadderTerm("thereafter", 17, 82),
        LadderTerm("total", 21, 19),
    )
    geometry = GeometryText(
        caption="Long-term Debt and Operating Lease",
        leadin="Senior notes and lease liabilities are presented together.",
        stubs=(
            "Aggregate maturities",
            "Total undiscounted lease payments",
            "Thereafter",
        ),
    )
    result = compete(geometry, terms=_TERMS, edges=_EDGES, ladder_terms=ladder)
    assert result.claims == ("lease_maturity",)
    states = {g.family: g.state for g in result.groups}
    assert states["debt_maturity"] == "attributed"
    untyped = compete(geometry, terms=_TERMS, edges=_EDGES, ladder_terms=())
    assert set(untyped.contested) == {"debt_maturity", "lease_maturity"}


def test_ladder_edge_terms_contest_a_lone_inverted_claim() -> None:
    from edgar_sec.engine.tables.extraction.signature_profiles import LadderTerm

    ladder = (LadderTerm("thereafter", 17, 82),)
    geometry = GeometryText(
        caption="Long-term Debt",
        leadin="Senior notes mature as follows.",
        stubs=(
            "Aggregate maturities",
            "Undiscounted lease payments",
            "Thereafter",
        ),
    )
    result = compete(geometry, terms=_TERMS, edges=_EDGES, ladder_terms=ladder)
    assert set(result.claims) == {"debt_maturity", "lease_maturity"}
    assert set(result.contested) == {"debt_maturity", "lease_maturity"}
    untyped = compete(geometry, terms=_TERMS, edges=_EDGES, ladder_terms=())
    assert untyped.claims == ("debt_maturity",)
    assert untyped.contested == ()


def test_presence_reach_claims_an_unclaimed_pension_geometry() -> None:
    terms = (
        SignatureTerm("pension", "stub", "pension obligation", 5.5, 30, 0),
        SignatureTerm("cash_flow", "stub", "cash flows", 0.4, 90, 80),
    )
    # The funded-status stub carries the pension gate's core anchor.
    geometry = GeometryText(stubs=("Pension obligation", "Funded status", "Cash flows"))
    result = compete(geometry, terms=terms, edges=())
    assert result.claims == ("pension",)
    assert result.groups[0].state == "reach"
    weak_terms = (
        SignatureTerm("pension", "stub", "pension obligation", 4.0, 30, 0),
        SignatureTerm("cash_flow", "stub", "cash flows", 0.4, 90, 80),
    )
    assert compete(geometry, terms=weak_terms, edges=()).claims == ()


def test_reach_requires_a_stub_share_of_the_family_evidence() -> None:
    terms = (
        SignatureTerm("pension", "caption", "pension", 4.5, 30, 0),
        SignatureTerm("pension", "stub", "pension obligation", 1.0, 30, 0),
        SignatureTerm("cash_flow", "stub", "cash flows", 0.4, 90, 80),
    )
    geometry = GeometryText(
        caption="Pension",
        stubs=("Pension obligation", "Funded status", "Cash flows"),
    )
    assert compete(geometry, terms=terms, edges=()).claims == ()
    stub_led = (
        SignatureTerm("pension", "caption", "pension", 1.0, 30, 0),
        SignatureTerm("pension", "stub", "pension obligation", 4.5, 30, 0),
        SignatureTerm("cash_flow", "stub", "cash flows", 0.4, 90, 80),
    )
    result = compete(geometry, terms=stub_led, edges=())
    assert result.claims == ("pension",)
    assert result.groups[0].state == "reach"


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


_UHAUL_PROSE = (
    "Recognition of Investment Income. Interest income from bonds and"
    " mortgage notes is recognized when earned. Dividends on common and"
    " preferred stocks are recognized on the ex-dividend dates. Realized"
    " gains and losses on the sale or exchange of investments are"
    " recognized at the trade date.\n"
    "Derivative Financial Instruments\n"
    "Our objective for holding derivative financial instruments is to"
    " manage interest rate risk exposure primarily through entering"
    " interest rate swap agreements and call options. We do not enter"
    " into these instruments for trading purposes. Counterparties to"
    " the interest rate swap agreements are major financial"
    " institutions. Derivatives are recognized at fair value on the"
    " balance sheet and are classified as prepaid expenses (asset) or"
    " accrued expenses (liability). Derivatives that are not designated"
    " as cash flow hedges for accounting purposes must be adjusted to"
    " fair value through income. If the derivative qualifies and is"
    " designated as a cash flow hedge, changes in its fair value will"
    " be recorded in accumulated other comprehensive income (loss) until"
    " the hedged item is recognized in earnings. See Note 11,"
    " Derivatives, of the Notes to Consolidated Financial Statements.\n"
    "Inventories and parts, net\n"
    "Inventories and parts, net were as follows:"
)


def test_leadin_segment_starts_at_the_last_heading() -> None:
    prose = (
        "Short-Term Borrowings\n"
        "The Company has a commercial paper facility.\n"
        "Long-Term Debt\n"
        "Long-term debt consisted of the following:"
    )
    assert leadin_segment(prose) == (
        "Long-Term Debt\nLong-term debt consisted of the following:"
    )
    assert lead_title_text(prose) == (
        "Long-Term Debt Long-term debt consisted of the following:"
    )


def test_leadin_segment_without_a_heading_is_unchanged() -> None:
    prose = (
        "During the first six months of 2014 and 2013, the total change"
        " in the fair value of the Company’s forward contracts recorded"
        " in other income (expense), net, was as follows:"
    )
    assert leadin_segment(prose) == prose
    assert lead_title_text(prose) == prose


def test_leadin_segment_ignores_furniture_labels_and_fragments() -> None:
    prose = (
        "The fair values of derivative instruments are shown below.\n"
        "NOTES TO CONSOLIDATED FINANCIAL STATEMENTS\n"
        "The following tabular disclosure does not include offsetting."
    )
    assert leadin_segment(prose) == prose
    labelled = (
        "Segment results for the prior year are discussed below.\n"
        "For the Nine Months Ended September 30, 2017\n"
        "Cash flow hedges were designated at inception."
    )
    assert leadin_segment(labelled) == labelled
    fragmented = (
        "Operating income increased due to pricing and mix.\n"
        "Asia\n"
        "Sales rose in the region during the year."
    )
    assert leadin_segment(fragmented) == fragmented


def test_leadin_segment_ignores_a_december_period_label() -> None:
    prose = (
        "Derivative Financial Instruments\n"
        "The Company uses derivatives to manage risk.\n"
        "For the Three Months Ended Dec. 31, 2024\n"
        "Inventories and parts, net\n"
        "Inventories and parts, net were as follows:"
    )
    assert leadin_segment(prose) == (
        "Inventories and parts, net\nInventories and parts, net were as follows:"
    )


def test_uhaul_leadin_segments_to_its_inventories_framing() -> None:
    segment = leadin_segment(_UHAUL_PROSE)
    assert segment == (
        "Inventories and parts, net\nInventories and parts, net were as follows:"
    )
    assert "derivative" not in segment.lower()
    assert lead_title_text(_UHAUL_PROSE) == (
        "Inventories and parts, net Inventories and parts, net were as follows:"
    )


def test_framing_prose_specimens_keep_their_leadin() -> None:
    first = (
        "Non-designated Hedging Strategy\n"
        "The Company enters into forward exchange contracts to hedge"
        " certain nonfunctional currency monetary accounts. The purpose"
        " of the Company’s foreign currency hedging activities is to"
        " protect the Company from risk that the eventual U.S. dollar"
        " equivalent cash flows from the nonfunctional currency monetary"
        " accounts will be adversely affected by changes in the exchange"
        " rates.\n"
        "For derivative instruments that are non-designated, the gain"
        " or loss on the derivative instrument subject to the hedged"
        " risk (i.e., nonfunctional currency monetary accounts) is"
        " recognized in other income (expense), net in current"
        " earnings.\n"
        "The Company had the following outstanding foreign currency"
        " forward contracts that hedge the fair value of nonfunctional"
        " currency monetary accounts (in millions):"
    )
    assert leadin_segment(first) == first
    assert lead_title_text(first).startswith(
        "Non-designated Hedging Strategy The Company enters into"
        " forward exchange contracts"
    )
    second = (
        "Notes to Consolidated Financial Statements, Continued\n"
        "The amount of gain (loss) for cash flow hedges recognized in"
        " accumulated other comprehensive income or loss, reclassified"
        " from accumulated other comprehensive income or loss into other"
        " revenues — other (effective portion) and interest expense"
        " (effective portion), and recognized in other revenues — other"
        " (ineffective portion) were as follows:"
    )
    assert leadin_segment(second) == second
    assert lead_title_text(second) == second.replace("\n", " ")


_PENSION_TERMS = (
    SignatureTerm("pension", "caption", "pension", 2.5, 40, 2),
    SignatureTerm("pension", "leadin", "pension", 2.5, 35, 1),
    SignatureTerm("pension", "stub", "pension expense", 2.5, 30, 0),
    SignatureTerm("pension", "stub", "actuarial", 2.5, 20, 0),
    SignatureTerm("pension", "stub", "equity securities", 2.5, 20, 0),
)


def test_pension_claim_without_core_anchor_is_gated() -> None:
    geometry = GeometryText(
        caption="Pension Benefits",
        leadin="The pension plan is described below.",
        stubs=("Pension expense", "Other expense", "Total"),
    )
    result = compete(geometry, terms=_PENSION_TERMS, edges=())
    assert "pension" not in result.claims
    trail = result.scores["pension"].evidence
    assert any(
        e.channel == "gate" and e.detail == "pension: no core anchor" for e in trail
    )


def test_pension_claim_with_core_anchor_stands() -> None:
    geometry = GeometryText(
        caption="Pension Benefits",
        leadin="The pension plan is described below.",
        stubs=("Pension expense", "Funded status", "Total"),
    )
    result = compete(geometry, terms=_PENSION_TERMS, edges=())
    assert result.claims == ("pension",)


def test_pension_oci_anchor_seats_the_claim() -> None:
    geometry = GeometryText(
        caption="Pension Benefits",
        leadin="The pension plan is described below.",
        stubs=(
            "Net actuarial loss",
            "Amortization of prior service credit",
            "Total recognized in other comprehensive income",
        ),
    )
    result = compete(geometry, terms=_PENSION_TERMS, edges=())
    assert result.claims == ("pension",)


def test_pension_prose_after_completion_seats_the_claim() -> None:
    # The lead text avoids the family's priced lead veto terms, so
    # the claim forms and the gate is the deciding act.
    bare = GeometryText(
        caption="Pension Benefits",
        leadin="The pension plan is described below.",
        lead="The following table presents the plan holdings.",
        stubs=("Equity securities", "Total"),
    )
    gated = compete(bare, terms=_PENSION_TERMS, edges=())
    assert "pension" not in gated.claims
    trail = gated.scores["pension"].evidence
    assert any(
        e.channel == "gate" and e.detail == "pension: no core anchor" for e in trail
    )
    completed = GeometryText(
        caption="Pension Benefits",
        leadin="The pension plan is described below.",
        lead="The following table presents the plan holdings.",
        prose_after="Assets of the pension plan are held in trust.",
        stubs=("Equity securities", "Total"),
    )
    seated = compete(completed, terms=_PENSION_TERMS, edges=())
    assert seated.claims == ("pension",)
