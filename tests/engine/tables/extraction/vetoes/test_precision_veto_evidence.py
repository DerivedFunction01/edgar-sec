"""Precision veto pass: the DERIV-1, DT-1, INV-1, F1,
credit dominance, and labor legs over gate-final claims."""

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
from edgar_sec.engine.tables.extraction.vetoes.precision_veto_evidence import (
    apply_precision_vetoes,
)


def _score(family, total=11.0):
    return FamilyScore(family, total, {"stub": total}, ())


def _result(families, groups=()):
    return CompetitionResult(
        claims=tuple(families),
        contested=tuple(families),
        scores={family: _score(family) for family in families},
        groups=groups,
    )


def _gate_details(result, family="derivatives_hedging"):
    return [
        item.detail for item in result.scores[family].evidence if item.channel == "gate"
    ]


def test_lead_convertible_removes_only_the_deriv_claim():
    geo = GeometryText(caption="Convertible senior notes")
    groups = (
        ClaimGroup(
            "derivatives_hedging", 11.0, "claimed", "primary", {"stub": 11.0}, (), 0.0
        ),
        ClaimGroup("debt_maturity", 5.0, "claimed", "primary", {"stub": 5.0}, (), 0.0),
    )
    results = apply_precision_vetoes(
        [geo], [_result(("derivatives_hedging", "debt_maturity"), groups=groups)]
    )
    assert "derivatives_hedging" not in results[0].claims
    assert "derivatives_hedging" not in results[0].contested
    assert "debt_maturity" in results[0].claims
    assert results[0].scores["derivatives_hedging"].total == 11.0
    assert _gate_details(results[0]) == ["precision veto: lead:convertible"]
    assert [group.family for group in results[0].groups] == ["debt_maturity"]


def test_header_securities_leg_fires():
    geo = GeometryText(headers=("Securities", "Fair value"))
    results = apply_precision_vetoes([geo], [_result(("derivatives_hedging",))])
    assert "derivatives_hedging" not in results[0].claims
    assert _gate_details(results[0]) == ["precision veto: hdr:securities"]


def test_stub_credit_leg_fires():
    geo = GeometryText(stubs=("Credit facility borrowings", "Interest expense"))
    results = apply_precision_vetoes([geo], [_result(("derivatives_hedging",))])
    assert "derivatives_hedging" not in results[0].claims
    assert _gate_details(results[0]) == ["precision veto: stub:credit"]


def test_header_level_leg_fires():
    geo = GeometryText(headers=("Level", "Total"))
    results = apply_precision_vetoes([geo], [_result(("derivatives_hedging",))])
    assert "derivatives_hedging" not in results[0].claims
    assert _gate_details(results[0]) == ["precision veto: hdr:level"]


def test_legs_report_in_priced_order():
    geo = GeometryText(
        caption="Convertible notes",
        headers=("Level",),
        stubs=("Credit agreement",),
    )
    results = apply_precision_vetoes([geo], [_result(("derivatives_hedging",))])
    assert _gate_details(results[0]) == [
        "precision veto: lead:convertible, stub:credit, hdr:level"
    ]


def test_no_leg_keeps_the_claim():
    geo = GeometryText(
        caption="Derivative instruments",
        headers=("Notional", "Fair value"),
        stubs=("Interest rate swaps", "Foreign currency contracts"),
    )
    results = apply_precision_vetoes([geo], [_result(("derivatives_hedging",))])
    assert "derivatives_hedging" in results[0].claims
    assert _gate_details(results[0]) == []


def test_tokens_are_family_scoped():
    geo = GeometryText(caption="Convertible senior notes")
    results = apply_precision_vetoes([geo], [_result(("debt_maturity",))])
    assert "debt_maturity" in results[0].claims


def test_stoplisted_header_words_do_not_fire():
    geo = GeometryText(headers=("The", "Table", "Financial", "Statements"))
    results = apply_precision_vetoes([geo], [_result(("derivatives_hedging",))])
    assert "derivatives_hedging" in results[0].claims


def test_short_tokens_never_match():
    geo = GeometryText(stubs=("Cr", "Le"), headers=("A", "An"))
    results = apply_precision_vetoes([geo], [_result(("derivatives_hedging",))])
    assert "derivatives_hedging" in results[0].claims


def _dt_details(result):
    return _gate_details(result, family="deferred_tax")


def test_pct_rows_leg_fires():
    geo = GeometryText(pct_row_share=0.25, stubs=("Net income",))
    results = apply_precision_vetoes([geo], [_result(("deferred_tax",))])
    assert "deferred_tax" not in results[0].claims
    assert _dt_details(results[0]) == ["precision veto: pct-rows"]


def test_eps_host_absence_leg_fires():
    geo = GeometryText(stubs=("Deferred tax assets", "Valuation allowance"))
    results = apply_precision_vetoes([geo], [_result(("deferred_tax",))])
    assert "deferred_tax" not in results[0].claims
    assert _dt_details(results[0]) == ["precision veto: host-absent:eps_reconciliation"]


def test_eps_host_present_via_grid_keeps_claim():
    geo = GeometryText(
        stubs=("Deferred tax assets",), grid_text="diluted shares outstanding"
    )
    results = apply_precision_vetoes([geo], [_result(("deferred_tax",))])
    assert "deferred_tax" in results[0].claims
    assert _dt_details(results[0]) == []


def test_stub_bigram_leg_fires():
    geo = GeometryText(stubs=("Income taxes payable",))
    results = apply_precision_vetoes([geo], [_result(("deferred_tax",))])
    assert "deferred_tax" not in results[0].claims
    assert _dt_details(results[0]) == ["precision veto: bigram:income taxes"]


def test_dt_legs_report_in_priced_order():
    geo = GeometryText(pct_row_share=0.5, stubs=("Income taxes", "Other"))
    results = apply_precision_vetoes([geo], [_result(("deferred_tax",))])
    assert _dt_details(results[0]) == ["precision veto: pct-rows, bigram:income taxes"]


def test_dt_no_leg_keeps_the_claim():
    geo = GeometryText(stubs=("Weighted average shares",))
    results = apply_precision_vetoes([geo], [_result(("deferred_tax",))])
    assert "deferred_tax" in results[0].claims
    assert _dt_details(results[0]) == []


def _inv_details(result):
    return _gate_details(result, family="inventory")


def test_credit_losses_host_leg_fires():
    geo = GeometryText(stubs=("Provision for credit losses",))
    results = apply_precision_vetoes([geo], [_result(("inventory",))])
    assert "inventory" not in results[0].claims
    assert _inv_details(results[0]) == [
        "precision veto: host:credit_losses_rollforward"
    ]


def test_lead_tables_leg_fires():
    geo = GeometryText(caption="Supplemental tables", stubs=("Finished goods",))
    results = apply_precision_vetoes([geo], [_result(("inventory",))])
    assert "inventory" not in results[0].claims
    assert _inv_details(results[0]) == ["precision veto: lead:tables"]


def test_lead_inventory_leg_fires():
    geo = GeometryText(notehead="Inventory", stubs=("Finished goods",))
    results = apply_precision_vetoes([geo], [_result(("inventory",))])
    assert "inventory" not in results[0].claims
    assert _inv_details(results[0]) == ["precision veto: lead:inventory"]


def test_inv_legs_report_in_priced_order():
    geo = GeometryText(caption="Inventory", stubs=("Provision for credit losses",))
    results = apply_precision_vetoes([geo], [_result(("inventory",))])
    assert _inv_details(results[0]) == [
        "precision veto: host:credit_losses_rollforward, lead:inventory"
    ]


def test_inv_no_leg_keeps_the_claim():
    geo = GeometryText(caption="Merchandise held", stubs=("Finished goods",))
    results = apply_precision_vetoes([geo], [_result(("inventory",))])
    assert "inventory" in results[0].claims
    assert _inv_details(results[0]) == []


def _credit_details(result):
    return _gate_details(result, family="credit_losses_rollforward")


def _scored_result(totals, groups=()):
    return CompetitionResult(
        claims=tuple(totals),
        contested=tuple(totals),
        scores={family: _score(family, total) for family, total in totals.items()},
        groups=groups,
    )


def test_dominant_co_claim_removes_only_the_credit_claim():
    geo = GeometryText(stubs=("Provision for credit losses",))
    groups = (
        ClaimGroup(
            "credit_losses_rollforward",
            5.0,
            "claimed",
            "primary",
            {"stub": 5.0},
            (),
            0.0,
        ),
        ClaimGroup(
            "cash_flow", 100.56, "claimed", "primary", {"stub": 100.56}, (), 0.0
        ),
    )
    results = apply_precision_vetoes(
        [geo],
        [
            _scored_result(
                {"credit_losses_rollforward": 5.0, "cash_flow": 100.56},
                groups=groups,
            )
        ],
    )
    assert "credit_losses_rollforward" not in results[0].claims
    assert "credit_losses_rollforward" not in results[0].contested
    assert "cash_flow" in results[0].claims
    assert results[0].scores["credit_losses_rollforward"].total == 5.0
    assert _credit_details(results[0]) == ["precision veto: dom:co-claim"]
    assert [group.family for group in results[0].groups] == ["cash_flow"]


def test_co_claim_inside_the_margin_keeps_the_claim():
    geo = GeometryText(stubs=("Provision for credit losses",))
    results = apply_precision_vetoes(
        [geo],
        [_scored_result({"credit_losses_rollforward": 5.0, "aoci_rollforward": 7.47})],
    )
    assert "credit_losses_rollforward" in results[0].claims
    assert _credit_details(results[0]) == []


def test_co_claim_at_the_margin_boundary_fires():
    geo = GeometryText(stubs=("Provision for credit losses",))
    results = apply_precision_vetoes(
        [geo],
        [_scored_result({"credit_losses_rollforward": 5.0, "cash_flow": 10.0})],
    )
    assert "credit_losses_rollforward" not in results[0].claims
    assert _credit_details(results[0]) == ["precision veto: dom:co-claim"]


def test_equal_co_claim_keeps_the_claim():
    geo = GeometryText(stubs=("Provision for credit losses",))
    results = apply_precision_vetoes(
        [geo],
        [
            _scored_result(
                {
                    "credit_losses_rollforward": 5.0,
                    "commitments_contingencies": 5.0,
                }
            )
        ],
    )
    assert "credit_losses_rollforward" in results[0].claims
    assert _credit_details(results[0]) == []


def test_sole_credit_claim_keeps_the_claim():
    geo = GeometryText(stubs=("Provision for credit losses",))
    results = apply_precision_vetoes(
        [geo], [_scored_result({"credit_losses_rollforward": 5.0})]
    )
    assert "credit_losses_rollforward" in results[0].claims
    assert _credit_details(results[0]) == []


def test_dominance_leg_is_credit_scoped():
    geo = GeometryText(stubs=("Finished goods",))
    results = apply_precision_vetoes(
        [geo], [_scored_result({"inventory": 5.0, "cash_flow": 100.56})]
    )
    assert "inventory" in results[0].claims
    assert _inv_details(results[0]) == []


def _int_details(result):
    return _gate_details(result, family="intangibles")


def _int_result(evidence, groups):
    families = ("intangibles", "goodwill_rollforward")
    scores = {family: _score(family) for family in families}
    scores["intangibles"] = FamilyScore(
        "intangibles", 20.55, {"lead_title": 20.55}, evidence
    )
    return CompetitionResult(
        claims=families,
        contested=families,
        scores=scores,
        groups=groups,
    )


def _int_groups():
    return (
        ClaimGroup(
            "intangibles", 20.55, "claimed", "head", {"lead_title": 20.55}, (), 0.0
        ),
        ClaimGroup(
            "goodwill_rollforward", 5.0, "claimed", "head", {"gate": 5.0}, (), 0.0
        ),
    )


_FAILED = (ClaimEvidence("form_test", "intangibles_composition failed", 0.0),)
_PASSED = (ClaimEvidence("form_test", "intangibles_composition passed", 3.0),)

_WALK_STUBS = (
    "Balance as of December 31, 2023",
    "Acquisition",
    "Currency translation and other",
    "Balance as of December 31, 2024",
)


def test_goodwill_host_leg_fires_on_a_goodwill_walk():
    geo = GeometryText(stubs=_WALK_STUBS)
    results = apply_precision_vetoes([geo], [_int_result(_FAILED, _int_groups())])
    assert "intangibles" not in results[0].claims
    assert "intangibles" not in results[0].contested
    assert "goodwill_rollforward" in results[0].claims
    assert _int_details(results[0]) == ["precision veto: host:goodwill_rollforward"]
    assert [group.family for group in results[0].groups] == ["goodwill_rollforward"]


def test_class_stub_evidence_spares_the_claim():
    geo = GeometryText(stubs=("Customer relationships", "Trade names", "Amortization"))
    results = apply_precision_vetoes([geo], [_int_result(_FAILED, _int_groups())])
    assert "intangibles" in results[0].claims
    assert _int_details(results[0]) == []


def test_no_goodwill_group_keeps_the_claim():
    groups = (_int_groups()[0],)
    geo = GeometryText(stubs=_WALK_STUBS)
    results = apply_precision_vetoes([geo], [_int_result(_FAILED, groups)])
    assert "intangibles" in results[0].claims
    assert _int_details(results[0]) == []


def test_composition_pass_keeps_the_claim():
    geo = GeometryText(stubs=_WALK_STUBS)
    results = apply_precision_vetoes([geo], [_int_result(_PASSED, _int_groups())])
    assert "intangibles" in results[0].claims
    assert _int_details(results[0]) == []


def test_unrecorded_composition_keeps_the_claim():
    geo = GeometryText(stubs=_WALK_STUBS)
    results = apply_precision_vetoes([geo], [_int_result((), _int_groups())])
    assert "intangibles" in results[0].claims
    assert _int_details(results[0]) == []


def _labor_details(result):
    return _gate_details(result, family="labor_contracts")


def test_employer_form_removes_only_the_labor_claim():
    geo = GeometryText(
        headers=(
            "Pension Protection Act",
            "EIN/Pension Plan Number",
            "FIP/RP Status(b)(c)",
        )
    )
    groups = (
        ClaimGroup(
            "labor_contracts", 5.0, "claimed", "primary", {"gate": 5.0}, (), 0.0
        ),
        ClaimGroup("pension", 44.34, "claimed", "primary", {"stub": 44.34}, (), 0.0),
    )
    results = apply_precision_vetoes(
        [geo], [_result(("labor_contracts", "pension"), groups=groups)]
    )
    assert "labor_contracts" not in results[0].claims
    assert "labor_contracts" not in results[0].contested
    assert "pension" in results[0].claims
    assert _labor_details(results[0]) == ["precision veto: hdr:employer-form"]
    assert [group.family for group in results[0].groups] == ["pension"]


def test_ein_slash_header_form_fires():
    geo = GeometryText(headers=("EIN/Plan number", "Zone status Year Ended"))
    results = apply_precision_vetoes([geo], [_result(("labor_contracts",))])
    assert "labor_contracts" not in results[0].claims
    assert _labor_details(results[0]) == ["precision veto: hdr:employer-form"]


def test_ein_token_header_fires():
    geo = GeometryText(headers=("EIN Pension", "Pension Protection Act Zone Status"))
    results = apply_precision_vetoes([geo], [_result(("labor_contracts",))])
    assert "labor_contracts" not in results[0].claims
    assert _labor_details(results[0]) == ["precision veto: hdr:employer-form"]


def test_fip_rp_phrase_alone_fires():
    geo = GeometryText(headers=("FIP/RP status pending/implemented",))
    results = apply_precision_vetoes([geo], [_result(("labor_contracts",))])
    assert "labor_contracts" not in results[0].claims
    assert _labor_details(results[0]) == ["precision veto: hdr:employer-form"]


def test_form_vocabulary_off_the_headers_keeps_the_claim():
    geo = GeometryText(
        caption="Pension Protection Act",
        headers=("Agreement", "Expiration"),
        stubs=("EIN plan number", "Zone status"),
    )
    results = apply_precision_vetoes([geo], [_result(("labor_contracts",))])
    assert "labor_contracts" in results[0].claims
    assert _labor_details(results[0]) == []


def test_true_claim_headers_keep_the_claim():
    geo = GeometryText(
        headers=(
            "Location",
            "Number of Unions",
            "Number of Union- Represented Employees",
            "Expiration Date",
        )
    )
    results = apply_precision_vetoes([geo], [_result(("labor_contracts",))])
    assert "labor_contracts" in results[0].claims
    assert _labor_details(results[0]) == []


def test_ein_inside_a_longer_word_keeps_the_claim():
    geo = GeometryText(headers=("Reinsurance recoverable", "Treaty year"))
    results = apply_precision_vetoes([geo], [_result(("labor_contracts",))])
    assert "labor_contracts" in results[0].claims
    assert _labor_details(results[0]) == []


def test_employer_form_is_family_scoped():
    geo = GeometryText(headers=("EIN/Plan number", "Zone status"))
    results = apply_precision_vetoes([geo], [_result(("pension",))])
    assert "pension" in results[0].claims


EPS = "eps_reconciliation"


def _eps_details(result):
    return _gate_details(result, family=EPS)


def _eps_result(channels):
    score = FamilyScore(EPS, sum(channels.values()), dict(channels), ())
    return CompetitionResult(claims=(EPS,), contested=(EPS,), scores={EPS: score})


def test_eps_restatement_face_statement_leg_fires():
    geo = GeometryText(
        headers=("As Previously Reported", "Adjustments", "As Restated"),
        stubs=("Consolidated statements of operations", "Net income"),
    )
    results = apply_precision_vetoes([geo], [_result((EPS,))])
    assert EPS not in results[0].claims
    assert _eps_details(results[0]) == ["precision veto: restatement:face-statement"]


def test_eps_restatement_tokens_without_a_face_statement_keep_the_claim():
    geo = GeometryText(
        headers=("As Previously Reported", "Adjustments", "As Restated"),
        stubs=("Weighted average shares", "Dilutive securities"),
    )
    results = apply_precision_vetoes([geo], [_result((EPS,))])
    assert EPS in results[0].claims
    assert _eps_details(results[0]) == []


def test_eps_face_statement_without_restatement_tokens_keeps_the_claim():
    geo = GeometryText(
        headers=("Year ended December 31", "Total"),
        stubs=("Consolidated balance sheet", "Total assets"),
    )
    results = apply_precision_vetoes([geo], [_result((EPS,))])
    assert EPS in results[0].claims
    assert _eps_details(results[0]) == []


def test_eps_partial_restatement_token_set_keeps_the_claim():
    geo = GeometryText(
        headers=("Adjustments", "As Restated"),
        stubs=("Consolidated statements of operations",),
    )
    results = apply_precision_vetoes([geo], [_result((EPS,))])
    assert EPS in results[0].claims
    assert _eps_details(results[0]) == []


def test_eps_context_only_leg_fires():
    results = apply_precision_vetoes(
        [GeometryText()], [_eps_result({"context": 18.18})]
    )
    assert EPS not in results[0].claims
    assert _eps_details(results[0]) == ["precision veto: context-only"]


def test_eps_own_text_mass_keeps_the_claim():
    results = apply_precision_vetoes(
        [GeometryText()], [_eps_result({"context": 18.18, "stub": 4.0})]
    )
    assert EPS in results[0].claims
    assert _eps_details(results[0]) == []


def test_eps_legs_report_in_priced_order():
    geo = GeometryText(
        headers=("As Previously Reported", "Adjustments", "As Restated"),
        stubs=("Consolidated statements of operations",),
    )
    results = apply_precision_vetoes([geo], [_eps_result({"context": 9.0})])
    assert _eps_details(results[0]) == [
        "precision veto: restatement:face-statement, context-only"
    ]


def test_eps_legs_are_family_scoped():
    geo = GeometryText(
        headers=("As Previously Reported", "Adjustments", "As Restated"),
        stubs=("Consolidated statements of operations",),
    )
    results = apply_precision_vetoes([geo], [_result(("debt_maturity",))])
    assert "debt_maturity" in results[0].claims
