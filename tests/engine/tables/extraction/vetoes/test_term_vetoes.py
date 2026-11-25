"""Term vetoes: specimen tests for the priced veto sets.

Removal semantics, any-hit scored composition, and the
set-completeness pin as ruled (Step 6 record; Step 4 build act).
"""

from __future__ import annotations

from edgar_sec.engine.tables.ascii_html.model.model import (
    ResolvedGrid,
    TableGeometry,
    TableRenderResult,
)
from edgar_sec.engine.tables.extraction.cascade.competition import compete
from edgar_sec.engine.tables.extraction.cascade.filing_competition import compete_filing
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    score_geometry,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
    geometry_text_from_table,
)
from edgar_sec.engine.tables.extraction.vetoes.term_vetoes import (
    TERM_VETOES,
    term_veto_hits,
    term_veto_hits_by_channel,
)
from edgar_sec.engine.tables.extraction.core.text.context import TableContext
from edgar_sec.engine.tables.extraction.core.subjects.signature_profiles import (
    SignatureTerm,
)
from edgar_sec.engine.tables.extraction.core.typed_rows import structure_table

_BS_TERMS = (
    SignatureTerm("balance_sheet", "caption", "balance sheet", 2.5, 40, 2),
    SignatureTerm("balance_sheet", "stub", "total assets", 2.5, 30, 0),
    SignatureTerm("balance_sheet", "stub", "total liabilities", 2.5, 30, 0),
    SignatureTerm("balance_sheet", "stub", "cash and equivalents", 2.5, 30, 0),
    SignatureTerm("cash_flow", "caption", "cash flows", 2.5, 40, 2),
    SignatureTerm("cash_flow", "stub", "net cash", 2.5, 30, 0),
    SignatureTerm("cash_flow", "stub", "operating activities", 2.5, 30, 0),
    SignatureTerm("cash_flow", "stub", "investing activities", 2.5, 30, 0),
)

_BS_STUBS = ("Total assets", "Total liabilities", "Cash and equivalents")


def _balance_sheet(**overrides) -> GeometryText:
    fields = {
        "caption": "Consolidated Balance Sheets",
        "stubs": _BS_STUBS,
    }
    fields.update(overrides)
    return GeometryText(**fields)


def test_hard_lead_hit_removes_the_claim() -> None:
    clean = compete(_balance_sheet(), terms=_BS_TERMS, edges=())
    assert clean.claims == ("balance_sheet",)
    vetoed = compete(
        _balance_sheet(
            lead="Consolidated Balance Sheets\n"
            "Issuer purchases of equity securities by the company."
        ),
        terms=_BS_TERMS,
        edges=(),
    )
    assert vetoed.claims == ()
    assert vetoed.groups == ()
    trail = vetoed.scores["balance_sheet"].evidence
    assert any(
        e.channel == "veto" and e.detail == "hard:issuer purchases" for e in trail
    )


_BS_COMPLETE_STUBS = _BS_STUBS + ("Total stockholders' equity",)


def test_lead_hard_hit_spares_gate_complete_balance_sheet() -> None:
    result = compete(
        _balance_sheet(
            stubs=_BS_COMPLETE_STUBS,
            lead="Risks related to the cost of complying with foreign laws.",
        ),
        terms=_BS_TERMS,
        edges=(),
    )
    assert result.claims == ("balance_sheet",)


def test_lead_hard_hit_bars_incomplete_balance_sheet() -> None:
    result = compete(
        _balance_sheet(
            lead="Risks related to the cost of complying with foreign laws.",
        ),
        terms=_BS_TERMS,
        edges=(),
    )
    assert result.claims == ()


def test_body_hard_hit_bars_gate_complete_balance_sheet() -> None:
    result = compete(
        _balance_sheet(
            stubs=_BS_COMPLETE_STUBS,
            lead="Consolidated Balance Sheets",
            grid_text="Risk factors are discussed elsewhere",
        ),
        terms=_BS_TERMS,
        edges=(),
    )
    assert result.claims == ()


def test_hits_by_channel_reports_the_lead_channel() -> None:
    geometry = _balance_sheet(
        lead="Risks related to the cost of complying with foreign laws.",
    )
    by_channel = term_veto_hits_by_channel(geometry)
    assert by_channel["balance_sheet"]["hard"] == {"lead": "the cost"}
    assert term_veto_hits(geometry)["balance_sheet"]["hard"] == "the cost"


def test_hard_body_hit_removes_the_claim() -> None:
    vetoed = compete(
        _balance_sheet(grid_text="Cash flows from operations were strong"),
        terms=_BS_TERMS,
        edges=(),
    )
    assert vetoed.claims == ()


def test_hard_term_is_channel_scoped() -> None:
    # 'issuer purchases' is priced on the lead channel only for
    # balance_sheet; the same words in the body do not veto.
    result = compete(
        _balance_sheet(grid_text="Issuer purchases were disclosed"),
        terms=_BS_TERMS,
        edges=(),
    )
    assert result.claims == ("balance_sheet",)


def test_hard_veto_bars_contested_and_creates_no_claim() -> None:
    stubs = _BS_STUBS + (
        "Net cash",
        "Operating activities",
        "Investing activities",
    )
    geometry = GeometryText(
        caption="Consolidated Balance Sheets and Statements of Cash Flows",
        stubs=stubs,
    )
    result = compete(geometry, terms=_BS_TERMS, edges=())
    assert set(result.claims) == {"balance_sheet", "cash_flow"}
    assert set(result.contested) == {"balance_sheet", "cash_flow"}
    vetoed = compete(
        GeometryText(
            caption="Consolidated Balance Sheets and Statements of Cash Flows",
            stubs=stubs,
            lead="Issuer purchases of equity securities.",
        ),
        terms=_BS_TERMS,
        edges=(),
    )
    # The vetoed score stays as foreign mass: the veto removes
    # the claim, not the evidence, so no new claim is created.
    assert vetoed.claims == ()
    assert vetoed.contested == ()
    assert all(g.family != "balance_sheet" for g in vetoed.groups)


_RP_TERMS = (
    SignatureTerm("related_party", "caption", "related party transactions", 2.5, 40, 2),
    *(
        SignatureTerm("related_party", "stub", f"related party line {i}", 2.5, 30, 0)
        for i in range(12)
    ),
)


def test_hard_veto_survives_inheritance_recompete() -> None:
    prior = GeometryText(
        caption="Related Party Transactions",
        stubs=tuple(f"Related party line {i}" for i in range(12)),
        note_title="Related party",
    )
    inherited = GeometryText(
        stubs=("Other", "Miscellaneous"),
        note_title="Related party",
        lead="The schedule follows.",
    )
    results = compete_filing([prior, inherited], terms=_RP_TERMS, edges=())
    assert results[0].claims == ("related_party",)
    assert results[1].claims == ("related_party",)
    vetoed_fragment = GeometryText(
        stubs=("Other", "Miscellaneous"),
        note_title="Related party",
        lead="Payments due by period are summarized.",
    )
    results = compete_filing([prior, vetoed_fragment], terms=_RP_TERMS, edges=())
    assert results[1].claims == ()


def test_scored_veto_is_any_hit_one_penalty() -> None:
    terms = (
        SignatureTerm(
            "tax_reconciliation", "caption", "tax reconciliation", 2.5, 40, 2
        ),
        SignatureTerm("tax_reconciliation", "stub", "federal rate", 2.5, 30, 0),
    )
    base = GeometryText(
        caption="Income Tax Reconciliation",
        stubs=("Federal rate",),
        lead="The reconciliation follows.",
    )
    hit = GeometryText(
        caption="Income Tax Reconciliation",
        stubs=("Federal rate",),
        lead="The provision for income taxes and effective tax effects.",
        grid_text="Income tax expense for the year",
    )
    base_total = score_geometry(base, terms)["tax_reconciliation"].total
    hit_score = score_geometry(hit, terms)["tax_reconciliation"]
    assert abs(base_total - hit_score.total - 1.5) < 1e-9
    term_evidence = [
        e
        for e in hit_score.evidence
        if e.channel == "veto" and e.detail.startswith("term:")
    ]
    assert len(term_evidence) == 1
    assert hit_score.by_channel["veto"] == -1.5


def test_lead_channel_from_production_seam() -> None:
    geometry = TableGeometry(
        table_index=0,
        render_result=TableRenderResult(
            ascii_text="",
            resolved_grid=ResolvedGrid(
                rows=(("Total assets", "100"), ("Total liabilities", "40")),
                column_alignments=(),
                column_widths=(),
                header_row_count=0,
            ),
            confidence=1.0,
        ),
    )
    prose = "Issuer purchases of equity securities are described."
    context = TableContext(geometry=geometry, prose_before=prose)
    text = geometry_text_from_table(structure_table(context))
    assert text.lead == text.caption + "\n" + prose
    hits = term_veto_hits(text)
    assert hits["balance_sheet"]["hard"] == "issuer purchases"


# Set completeness: counts per (family, channel, tier) from the
# priced records after the ruled holds and release; 546 rows.
_GROUP_COUNTS = {
    ("aoci_rollforward", "body", "hard"): 4,
    ("aoci_rollforward", "body", "scored"): 13,
    ("aoci_rollforward", "lead", "scored"): 5,
    ("balance_sheet", "body", "hard"): 30,
    ("balance_sheet", "body", "scored"): 32,
    ("balance_sheet", "lead", "hard"): 22,
    ("balance_sheet", "lead", "scored"): 20,
    ("cash_flow", "body", "hard"): 4,
    ("cash_flow", "body", "scored"): 20,
    ("cash_flow", "lead", "hard"): 12,
    ("cash_flow", "lead", "scored"): 14,
    ("comprehensive_income", "body", "hard"): 1,
    ("comprehensive_income", "body", "scored"): 13,
    ("comprehensive_income", "lead", "scored"): 11,
    ("debt_maturity", "body", "hard"): 1,
    ("debt_maturity", "lead", "hard"): 1,
    ("debt_maturity", "lead", "scored"): 11,
    ("deferred_tax", "body", "hard"): 3,
    ("deferred_tax", "body", "scored"): 7,
    ("deferred_tax", "lead", "hard"): 6,
    ("deferred_tax", "lead", "scored"): 5,
    ("derivatives_hedging", "body", "hard"): 4,
    ("derivatives_hedging", "body", "scored"): 4,
    ("derivatives_hedging", "lead", "hard"): 2,
    ("derivatives_hedging", "lead", "scored"): 5,
    ("eps_reconciliation", "body", "hard"): 10,
    ("eps_reconciliation", "body", "scored"): 9,
    ("eps_reconciliation", "lead", "hard"): 3,
    ("eps_reconciliation", "lead", "scored"): 23,
    ("equity_statement", "body", "hard"): 9,
    ("equity_statement", "body", "scored"): 16,
    ("equity_statement", "lead", "hard"): 7,
    ("equity_statement", "lead", "scored"): 15,
    ("fair_value", "body", "scored"): 2,
    ("income_statement", "body", "hard"): 1,
    ("income_statement", "body", "scored"): 23,
    ("income_statement", "lead", "hard"): 4,
    ("income_statement", "lead", "scored"): 12,
    ("intangibles", "body", "hard"): 6,
    ("intangibles", "body", "scored"): 3,
    ("intangibles", "lead", "hard"): 6,
    ("intangibles", "lead", "scored"): 10,
    ("inventory", "lead", "hard"): 1,
    ("inventory", "lead", "scored"): 2,
    ("lease_maturity", "body", "hard"): 5,
    ("lease_maturity", "body", "scored"): 6,
    ("lease_maturity", "lead", "hard"): 5,
    ("lease_maturity", "lead", "scored"): 6,
    ("pension", "body", "hard"): 6,
    ("pension", "body", "scored"): 13,
    ("pension", "lead", "hard"): 5,
    ("pension", "lead", "scored"): 9,
    ("ppe", "body", "hard"): 1,
    ("ppe", "lead", "scored"): 4,
    ("related_party", "body", "hard"): 2,
    ("related_party", "body", "scored"): 2,
    ("related_party", "lead", "hard"): 3,
    ("related_party", "lead", "scored"): 5,
    ("segment_reporting", "body", "hard"): 2,
    ("segment_reporting", "body", "scored"): 2,
    ("segment_reporting", "lead", "scored"): 4,
    ("stock_comp_rollforward", "body", "hard"): 5,
    ("stock_comp_rollforward", "body", "scored"): 5,
    ("stock_comp_rollforward", "lead", "hard"): 4,
    ("stock_comp_rollforward", "lead", "scored"): 10,
    ("tax_reconciliation", "body", "hard"): 8,
    ("tax_reconciliation", "body", "scored"): 4,
    ("tax_reconciliation", "lead", "hard"): 15,
    ("tax_reconciliation", "lead", "scored"): 3,
}


def _all_rows() -> set[tuple[str, str, str, str]]:
    return {
        (spec.family, term, spec.channel, spec.tier)
        for spec in TERM_VETOES
        for term in spec.terms
    }


def test_veto_set_is_complete_as_ruled() -> None:
    rows = _all_rows()
    assert len(rows) == 546
    counts: dict[tuple[str, str, str], int] = {}
    for family, _term, channel, tier in rows:
        key = (family, channel, tier)
        counts[key] = counts.get(key, 0) + 1
    assert counts == _GROUP_COUNTS
    tiers = [tier for _f, _t, _c, tier in rows]
    assert tiers.count("hard") == 198
    assert tiers.count("scored") == 348


def test_eps_v3_terms_leave_lead_hard() -> None:
    rows = _all_rows()
    # V3 (EPS recall packet): the three terms leave the
    # eps_reconciliation lead/hard set; the rest stands.
    dropped = {"acquisition", "share of", "or for"}
    assert not any(("eps_reconciliation", t, "lead", "hard") in rows for t in dropped)
    kept = (
        "comprehensive loss",
        "discussion and analysis",
        "issuer purchases",
    )
    assert all(("eps_reconciliation", t, "lead", "hard") in rows for t in kept)


def test_eps_fiscal_year_term_leaves_lead_hard() -> None:
    rows = _all_rows()
    # FINAL-F (eps_reconciliation enlarged-set packet):
    # "fiscal year" leaves the eps_reconciliation lead/hard
    # set; the three remaining terms stand.
    assert ("eps_reconciliation", "fiscal year", "lead", "hard") not in rows
    kept = (
        "comprehensive loss",
        "discussion and analysis",
        "issuer purchases",
    )
    assert all(("eps_reconciliation", t, "lead", "hard") in rows for t in kept)


def test_deferred_tax_revenue_lead_hard_row_removed() -> None:
    rows = _all_rows()
    # VA1 (DT recall packet): "revenue" leaves the deferred_tax
    # lead/hard set; the rest of the set stands as priced.
    assert ("deferred_tax", "revenue", "lead", "hard") not in rows
    assert ("deferred_tax", "cash flow", "lead", "hard") in rows
    assert ("deferred_tax", "depreciation", "lead", "hard") in rows


def test_build_act_exclusions_of_record() -> None:
    rows = _all_rows()
    families = {family for family, _t, _c, _tier in rows}
    # No row keys under the retired short spelling: the family
    # lands only as aoci_rollforward (Step 3's spelling fix).
    assert "aoci" not in families
    assert "commitments_contingencies" not in families
    furniture_only = {
        ("intangibles", "reportable segment"),
        ("segment_reporting", "form 10-k"),
        ("eps_reconciliation", "comprehensive income"),
        ("balance_sheet", "shares outstanding"),
        ("balance_sheet", "index to"),
    }
    assert not any((f, t) in furniture_only for f, t, _c, _tier in rows)
    # The eps sensitivity row is not admitted at HARD: it touches
    # one sweep-all true; the firm-named row was rejected outright.
    assert ("eps_reconciliation", "total", "body", "hard") not in rows
    assert not any(t == "cpas, pllc" for _f, t, _c, _tier in rows)


def test_aoci_held_rows_released_hard_as_repriced() -> None:
    rows = _all_rows()
    # Of the 12 held AOCI additions, re-priced under the single
    # spelling only the two zero-touch rows land at HARD.
    released = {
        ("aoci_rollforward", "net sales", "body"),
        ("aoci_rollforward", "three months ended march", "body"),
    }
    assert all((*row, "hard") in rows for row in released)
    # The other ten touch measured aoci_rollforward trues on the
    # unified base (release record) and stay out of HARD.
    held_back = {
        ("aoci_rollforward", "assets", "lead"),
        ("aoci_rollforward", "ended march", "lead"),
        ("aoci_rollforward", "months ended", "lead"),
        ("aoci_rollforward", "three months", "lead"),
        ("aoci_rollforward", "balance at end of period", "body"),
        ("aoci_rollforward", "beginning balance", "body"),
        ("aoci_rollforward", "change", "body"),
        ("aoci_rollforward", "interest expense", "body"),
        ("aoci_rollforward", "period", "body"),
        ("aoci_rollforward", "total", "body"),
    }
    assert all((*row, "hard") not in rows for row in held_back)


def test_dagger_rows_landed_hard_as_priced() -> None:
    rows = _all_rows()
    dagger_rows = {
        ("income_statement", "products and", "lead"),
        ("tax_reconciliation", "three months", "body"),
        ("tax_reconciliation", "months ended", "body"),
        ("stock_comp_rollforward", "year ended", "body"),
        ("deferred_tax", "credit losses", "lead"),
        ("debt_maturity", "senior secured", "lead"),
    }
    assert all((*row, "hard") in rows for row in dagger_rows)


def test_aoci_own_vocabulary_hard_terms_released() -> None:
    rows = _all_rows()
    # The aoci_rollforward residual packet removes the family's
    # own-vocabulary hard terms — they bar genuine rollforward
    # grids on their own component and movement vocabulary.
    released = {
        ("aoci_rollforward", "benefit plans", "body"),
        ("aoci_rollforward", "tax benefit", "body"),
        ("aoci_rollforward", "income tax", "lead"),
        ("aoci_rollforward", "reclassification", "lead"),
    }
    assert all((*row, "hard") not in rows for row in released)
    # The protective aoci hard terms stand: "three months ended
    # march" alone bars generic balance-walk tables with no
    # AOCI subject from seating as aoci_rollforward.
    kept = {
        ("aoci_rollforward", "equity securities", "body"),
        ("aoci_rollforward", "years", "body"),
        ("aoci_rollforward", "net sales", "body"),
        ("aoci_rollforward", "three months ended march", "body"),
    }
    assert all((*row, "hard") in rows for row in kept)


def test_current_assets_rows_retiered_to_scored() -> None:
    rows = _all_rows()
    # On the body channel the term is the family's own grid
    # vocabulary (42 true touches on v3); the s7 conversion
    # build re-tiers the lead row the same way.
    assert ("balance_sheet", "current assets", "body", "hard") not in rows
    assert ("balance_sheet", "current assets", "body", "scored") in rows
    assert ("balance_sheet", "current assets", "lead", "hard") not in rows
    assert ("balance_sheet", "current assets", "lead", "scored") in rows


def test_issuer_purchases_rows_exactly_the_six_measured_families() -> None:
    rows = _all_rows()
    issuer = {
        (family, channel, tier)
        for family, term, channel, tier in rows
        if term == "issuer purchases"
    }
    assert issuer == {
        (family, "lead", "hard")
        for family in (
            "balance_sheet",
            "cash_flow",
            "eps_reconciliation",
            "equity_statement",
            "stock_comp_rollforward",
            "tax_reconciliation",
        )
    }
