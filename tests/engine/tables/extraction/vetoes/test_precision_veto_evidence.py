"""Precision veto pass: the DERIV-1, DT-1, INV-1, and
credit dominance legs over gate-final claims."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
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
        ClaimGroup("cash_flow", 100.56, "claimed", "primary", {"stub": 100.56}, (), 0.0),
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
        [
            _scored_result(
                {"credit_losses_rollforward": 5.0, "aoci_rollforward": 7.47}
            )
        ],
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
