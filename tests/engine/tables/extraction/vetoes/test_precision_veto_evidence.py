"""Precision veto pass: the DERIV-1, DT-1, INV-1, and
DEBT-P9 legs over gate-final claims of their families."""

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
from edgar_sec.engine.tables.extraction.vetoes.ppe_veto_evidence import (
    ClaimStage,
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


def _apply(geometries, results, stages=None):
    if stages is None:
        stages = tuple(
            ClaimStage(claims=result.claims, scores=result.scores) for result in results
        )
    return apply_precision_vetoes(geometries, results, stages)


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
    results = _apply(
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
    results = _apply([geo], [_result(("derivatives_hedging",))])
    assert "derivatives_hedging" not in results[0].claims
    assert _gate_details(results[0]) == ["precision veto: hdr:securities"]


def test_stub_credit_leg_fires():
    geo = GeometryText(stubs=("Credit facility borrowings", "Interest expense"))
    results = _apply([geo], [_result(("derivatives_hedging",))])
    assert "derivatives_hedging" not in results[0].claims
    assert _gate_details(results[0]) == ["precision veto: stub:credit"]


def test_header_level_leg_fires():
    geo = GeometryText(headers=("Level", "Total"))
    results = _apply([geo], [_result(("derivatives_hedging",))])
    assert "derivatives_hedging" not in results[0].claims
    assert _gate_details(results[0]) == ["precision veto: hdr:level"]


def test_legs_report_in_priced_order():
    geo = GeometryText(
        caption="Convertible notes",
        headers=("Level",),
        stubs=("Credit agreement",),
    )
    results = _apply([geo], [_result(("derivatives_hedging",))])
    assert _gate_details(results[0]) == [
        "precision veto: lead:convertible, stub:credit, hdr:level"
    ]


def test_no_leg_keeps_the_claim():
    geo = GeometryText(
        caption="Derivative instruments",
        headers=("Notional", "Fair value"),
        stubs=("Interest rate swaps", "Foreign currency contracts"),
    )
    results = _apply([geo], [_result(("derivatives_hedging",))])
    assert "derivatives_hedging" in results[0].claims
    assert _gate_details(results[0]) == []


def test_tokens_are_family_scoped():
    geo = GeometryText(caption="Convertible senior notes")
    results = _apply([geo], [_result(("debt_maturity",))])
    assert "debt_maturity" in results[0].claims


def test_stoplisted_header_words_do_not_fire():
    geo = GeometryText(headers=("The", "Table", "Financial", "Statements"))
    results = _apply([geo], [_result(("derivatives_hedging",))])
    assert "derivatives_hedging" in results[0].claims


def test_short_tokens_never_match():
    geo = GeometryText(stubs=("Cr", "Le"), headers=("A", "An"))
    results = _apply([geo], [_result(("derivatives_hedging",))])
    assert "derivatives_hedging" in results[0].claims


def _dt_details(result):
    return _gate_details(result, family="deferred_tax")


def test_pct_rows_leg_fires():
    geo = GeometryText(pct_row_share=0.25, stubs=("Net income",))
    results = _apply([geo], [_result(("deferred_tax",))])
    assert "deferred_tax" not in results[0].claims
    assert _dt_details(results[0]) == ["precision veto: pct-rows"]


def test_eps_host_absence_leg_fires():
    geo = GeometryText(stubs=("Deferred tax assets", "Valuation allowance"))
    results = _apply([geo], [_result(("deferred_tax",))])
    assert "deferred_tax" not in results[0].claims
    assert _dt_details(results[0]) == ["precision veto: host-absent:eps_reconciliation"]


def test_eps_host_present_via_grid_keeps_claim():
    geo = GeometryText(
        stubs=("Deferred tax assets",), grid_text="diluted shares outstanding"
    )
    results = _apply([geo], [_result(("deferred_tax",))])
    assert "deferred_tax" in results[0].claims
    assert _dt_details(results[0]) == []


def test_stub_bigram_leg_fires():
    geo = GeometryText(stubs=("Income taxes payable",))
    results = _apply([geo], [_result(("deferred_tax",))])
    assert "deferred_tax" not in results[0].claims
    assert _dt_details(results[0]) == ["precision veto: bigram:income taxes"]


def test_dt_legs_report_in_priced_order():
    geo = GeometryText(pct_row_share=0.5, stubs=("Income taxes", "Other"))
    results = _apply([geo], [_result(("deferred_tax",))])
    assert _dt_details(results[0]) == ["precision veto: pct-rows, bigram:income taxes"]


def test_dt_no_leg_keeps_the_claim():
    geo = GeometryText(stubs=("Weighted average shares",))
    results = _apply([geo], [_result(("deferred_tax",))])
    assert "deferred_tax" in results[0].claims
    assert _dt_details(results[0]) == []


def _inv_details(result):
    return _gate_details(result, family="inventory")


def test_credit_losses_host_leg_fires():
    geo = GeometryText(stubs=("Provision for credit losses",))
    results = _apply([geo], [_result(("inventory",))])
    assert "inventory" not in results[0].claims
    assert _inv_details(results[0]) == [
        "precision veto: host:credit_losses_rollforward"
    ]


def test_lead_tables_leg_fires():
    geo = GeometryText(caption="Supplemental tables", stubs=("Finished goods",))
    results = _apply([geo], [_result(("inventory",))])
    assert "inventory" not in results[0].claims
    assert _inv_details(results[0]) == ["precision veto: lead:tables"]


def test_lead_inventory_leg_fires():
    geo = GeometryText(notehead="Inventory", stubs=("Finished goods",))
    results = _apply([geo], [_result(("inventory",))])
    assert "inventory" not in results[0].claims
    assert _inv_details(results[0]) == ["precision veto: lead:inventory"]


def test_inv_legs_report_in_priced_order():
    geo = GeometryText(caption="Inventory", stubs=("Provision for credit losses",))
    results = _apply([geo], [_result(("inventory",))])
    assert _inv_details(results[0]) == [
        "precision veto: host:credit_losses_rollforward, lead:inventory"
    ]


def test_inv_no_leg_keeps_the_claim():
    geo = GeometryText(caption="Merchandise held", stubs=("Finished goods",))
    results = _apply([geo], [_result(("inventory",))])
    assert "inventory" in results[0].claims
    assert _inv_details(results[0]) == []


def _debt_details(result):
    return _gate_details(result, family="debt_maturity")


def _debt_stage(channels, evidence=()):
    score = FamilyScore("debt_maturity", 9.65, channels, evidence)
    return (ClaimStage(claims=("debt_maturity",), scores={"debt_maturity": score}),)


def _debt_geometry(**overrides):
    fields = {
        "stubs": ("Bank debt", "Current portion", "Long-term bank debt"),
        "numeric_cells": 12,
    }
    fields.update(overrides)
    return GeometryText(**fields)


def test_debt_leadin_only_leg_fires():
    geo = _debt_geometry()
    groups = (
        ClaimGroup(
            "debt_maturity", 9.65, "claimed", "primary", {"leadin": 9.65}, (), 0.0
        ),
    )
    results = _apply(
        [geo],
        [_result(("debt_maturity",), groups=groups)],
        stages=_debt_stage({"leadin": 9.65}),
    )
    assert "debt_maturity" not in results[0].claims
    assert "debt_maturity" not in results[0].contested
    assert results[0].groups == ()
    assert results[0].scores["debt_maturity"].total == 11.0
    assert _debt_details(results[0]) == ["precision veto: leadin-only"]


def test_debt_leg_reads_the_stage_not_the_final_score():
    geo = _debt_geometry()
    results = _apply(
        [geo],
        [_result(("debt_maturity",))],
        stages=_debt_stage({"stub": 9.65}),
    )
    assert "debt_maturity" in results[0].claims
    assert _debt_details(results[0]) == []


def test_debt_missing_own_stage_score_keeps_the_claim():
    geo = _debt_geometry()
    stages = (ClaimStage(claims=("debt_maturity",), scores={}),)
    results = _apply([geo], [_result(("debt_maturity",))], stages=stages)
    assert "debt_maturity" in results[0].claims


def test_debt_ladder_passed_keeps_the_claim():
    geo = _debt_geometry()
    evidence = (ClaimEvidence("form_test", "debt_maturity_year_ladder passed", 3.0),)
    results = _apply(
        [geo],
        [_result(("debt_maturity",))],
        stages=_debt_stage({"leadin": 9.65}, evidence),
    )
    assert "debt_maturity" in results[0].claims
    assert _debt_details(results[0]) == []


def test_debt_admission_support_keeps_the_claim():
    geo = _debt_geometry()
    results = _apply(
        [geo],
        [_result(("debt_maturity",))],
        stages=_debt_stage({"leadin": 7.24, "admission": 5.0}),
    )
    assert "debt_maturity" in results[0].claims


def test_debt_year_stub_keeps_the_claim():
    geo = _debt_geometry(stubs=("2027", "2028", "2029"))
    results = _apply(
        [geo],
        [_result(("debt_maturity",))],
        stages=_debt_stage({"leadin": 9.65}),
    )
    assert "debt_maturity" in results[0].claims


def test_debt_thereafter_stub_keeps_the_claim():
    geo = _debt_geometry(stubs=("2027", "Thereafter"))
    results = _apply(
        [geo],
        [_result(("debt_maturity",))],
        stages=_debt_stage({"leadin": 9.65}),
    )
    assert "debt_maturity" in results[0].claims


def test_debt_numeric_mass_over_cap_keeps_the_claim():
    geo = _debt_geometry(numeric_cells=13)
    results = _apply(
        [geo],
        [_result(("debt_maturity",))],
        stages=_debt_stage({"leadin": 9.65}),
    )
    assert "debt_maturity" in results[0].claims


def test_debt_header_year_amount_pair_keeps_the_claim():
    geo = _debt_geometry(headers=("2026", "1,000"))
    results = _apply(
        [geo],
        [_result(("debt_maturity",))],
        stages=_debt_stage({"leadin": 9.65}),
    )
    assert "debt_maturity" in results[0].claims


def test_debt_header_year_after_year_still_fires():
    geo = _debt_geometry(headers=("2026", "2027"))
    results = _apply(
        [geo],
        [_result(("debt_maturity",))],
        stages=_debt_stage({"leadin": 9.65}),
    )
    assert "debt_maturity" not in results[0].claims
    assert _debt_details(results[0]) == ["precision veto: leadin-only"]
