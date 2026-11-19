"""Income-statement set-level stage: legs and firing order."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.competition import GeometryText
from edgar_sec.engine.tables.extraction.geometry_scoring import (
    CompetitionResult,
    FamilyScore,
)
from edgar_sec.engine.tables.extraction.income_statement_setlevel_evidence import (
    apply_income_statement_assignment,
    core_share,
    net_values,
)

_IS = "income_statement"
_COMPLETE = ("Revenues", "Operating expenses", "Other income, net", "Net income")
_BALANCE = ("Total assets", "Total liabilities", "Total equity")


def _geometry(stubs=(), grid_text="", note="Note 27", item="ITEM 8"):
    return GeometryText(
        stubs=stubs,
        grid_text=grid_text,
        section_item=item,
        note_title=note,
    )


def _result(claims=(), contested=(), totals=None):
    scores = {
        family: FamilyScore(family, total, {}, ())
        for family, total in (totals or {}).items()
    }
    return CompetitionResult(claims=claims, contested=contested, scores=scores)


def _gate_details(result):
    return [
        entry.detail
        for score in result.scores.values()
        for entry in score.evidence
        if entry.channel == "gate"
    ]


def test_no_income_claim_returns_results_unchanged():
    results = [_result(claims=("cash_flow",), totals={"cash_flow": 3.0})]
    out = apply_income_statement_assignment([_geometry()], results)
    assert out == results
    assert out[0] is results[0]


def test_routing_refuses_foreign_complete_claim():
    geometry = _geometry(stubs=_BALANCE)
    results = [_result(claims=(_IS,), totals={_IS: 7.5})]
    out = apply_income_statement_assignment([geometry], results)
    assert out[0].claims == ()
    assert _gate_details(out[0]) == [
        "income statement assignment: cross-family routing"
    ]


def test_routing_silent_when_cluster_gate_complete():
    geometry = _geometry(stubs=_COMPLETE)
    results = [_result(claims=(_IS,), totals={_IS: 7.5})]
    out = apply_income_statement_assignment([geometry], results)
    assert out[0].claims == (_IS,)
    assert _gate_details(out[0]) == []


def test_uniqueness_core_share_decides_on_tied_keys():
    high = _geometry(
        stubs=("Revenues", "Operating expenses", "Interest expense", "Net income")
    )
    low = _geometry(
        stubs=(
            "Total revenues",
            "Total operating expenses",
            "Other income, net",
            "Net earnings",
        ),
        note="Note 28",
    )
    results = [
        _result(claims=(_IS,), totals={_IS: 10.0}),
        _result(claims=(_IS,), totals={_IS: 10.0}),
    ]
    out = apply_income_statement_assignment([high, low], results)
    assert out[0].claims == (_IS,)
    assert out[1].claims == ()
    assert _gate_details(out[1]) == [
        "income statement assignment: within-filing uniqueness"
    ]


def test_dominant_cluster_refuses_outside_contested_claim():
    anchor = _geometry()
    outside = _geometry(stubs=_COMPLETE, item="ITEM 15")
    results = [
        _result(claims=("balance_sheet",), totals={"balance_sheet": 9.0}),
        _result(contested=(_IS,), totals={_IS: 8.0}),
    ]
    out = apply_income_statement_assignment([anchor, outside], results)
    assert out[0].claims == ("balance_sheet",)
    assert out[1].contested == ()
    assert _gate_details(out[1]) == [
        "income statement assignment: outside dominant cluster"
    ]


def test_dominant_cluster_silent_when_anchor_clusters_tie():
    first = _geometry(note="Note 27")
    second = _geometry(note="Note 28")
    claim = _geometry(stubs=_COMPLETE, note="Note 29")
    results = [
        _result(claims=("balance_sheet",), totals={"balance_sheet": 9.0}),
        _result(claims=("balance_sheet",), totals={"balance_sheet": 9.0}),
        _result(claims=(_IS,), totals={_IS: 8.0}),
    ]
    out = apply_income_statement_assignment([first, second, claim], results)
    assert out[2].claims == (_IS,)


def test_ties_refuses_untied_claim():
    claim = _geometry(stubs=_COMPLETE, grid_text="Net income | 1,234 | 5,678")
    anchor = _geometry(grid_text="Net income | 9,999", note="Note 28")
    results = [
        _result(claims=(_IS,), totals={_IS: 8.0}),
        _result(claims=("cash_flow",), totals={"cash_flow": 9.0}),
    ]
    out = apply_income_statement_assignment([claim, anchor], results)
    assert out[0].claims == ()
    assert _gate_details(out[0]) == [
        "income statement assignment: cross-statement ties"
    ]


def test_ties_silent_when_tied():
    claim = _geometry(stubs=_COMPLETE, grid_text="Net income | 1,234")
    anchor = _geometry(grid_text="Net income | 1,234", note="Note 28")
    results = [
        _result(claims=(_IS,), totals={_IS: 8.0}),
        _result(claims=("cash_flow",), totals={"cash_flow": 9.0}),
    ]
    out = apply_income_statement_assignment([claim, anchor], results)
    assert out[0].claims == (_IS,)


def test_refusal_keeps_other_claims_and_score_totals():
    geometry = _geometry(stubs=_BALANCE)
    results = [
        _result(claims=(_IS, "cash_flow"), totals={_IS: 7.5, "cash_flow": 3.0})
    ]
    out = apply_income_statement_assignment([geometry], results)
    assert out[0].claims == ("cash_flow",)
    assert out[0].scores[_IS].total == 7.5
    assert out[0].scores["cash_flow"].total == 3.0


def test_core_share_reads_carried_vocabulary():
    geometry = _geometry(stubs=("Net income", "Revenues", "Some other row"))
    assert core_share(geometry) == 2 / 13
    assert core_share(_geometry()) == 0.0


def test_net_values_canonicalizes_and_filters():
    geometry = _geometry(
        grid_text=(
            "Net income | (1,234) | 12 | 123.45\n"
            "Revenues | 7,890\n"
            "Net loss | 5,678"
        )
    )
    assert net_values(geometry) == {"1234", "5678"}
