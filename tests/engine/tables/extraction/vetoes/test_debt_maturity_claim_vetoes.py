"""Debt-maturity claim vetoes: the three priced rule-form
conditions refuse the claim; every other geometry passes."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_scoring import (
    CompetitionResult,
    FamilyScore,
)
from edgar_sec.engine.tables.extraction.cascade.geometry.geometry_text import (
    GeometryText,
)
from edgar_sec.engine.tables.extraction.vetoes.debt_maturity_claim_vetoes import (
    apply_debt_maturity_claim_vetoes,
    debt_maturity_veto_reason,
)


def _claimed(geometry: GeometryText) -> CompetitionResult:
    score = FamilyScore("debt_maturity", 12.0, {"stub": 12.0}, ())
    return CompetitionResult(
        claims=("debt_maturity",), contested=(), scores={"debt_maturity": score}
    )


def test_headers_n_26_refuses() -> None:
    geometry = GeometryText(headers=tuple(f"H{i}" for i in range(26)))
    assert debt_maturity_veto_reason(geometry) == "debt veto: headers_n=26"


def test_headers_n_25_passes() -> None:
    geometry = GeometryText(headers=tuple(f"H{i}" for i in range(25)))
    assert debt_maturity_veto_reason(geometry) is None


def test_cash_flow_per_share_hard_hit_refuses() -> None:
    geometry = GeometryText(caption="Data per share")
    assert (
        debt_maturity_veto_reason(geometry)
        == "debt veto: cash_flow hard per share"
    )


def test_total_header_with_maturity_scored_hit_refuses() -> None:
    geometry = GeometryText(
        caption="Debt maturity schedule", headers=("Fiscal year", "Total")
    )
    assert (
        debt_maturity_veto_reason(geometry)
        == "debt veto: Total header with maturity scored hit"
    )


def test_total_header_without_maturity_hit_passes() -> None:
    geometry = GeometryText(caption="Borrowings", headers=("Fiscal year", "Total"))
    assert debt_maturity_veto_reason(geometry) is None


def test_maturity_hit_without_total_header_passes() -> None:
    geometry = GeometryText(
        caption="Debt maturity schedule", headers=("Fiscal year", "Amount")
    )
    assert debt_maturity_veto_reason(geometry) is None


def test_apply_removes_only_the_vetoed_claim() -> None:
    vetoed = GeometryText(headers=tuple(f"H{i}" for i in range(26)))
    spared = GeometryText(caption="Borrowings", headers=("Year", "Amount"))
    results = apply_debt_maturity_claim_vetoes(
        [vetoed, spared], [_claimed(vetoed), _claimed(spared)]
    )
    assert results[0].claims == ()
    assert results[1].claims == ("debt_maturity",)
    evidence = results[0].scores["debt_maturity"].evidence
    assert evidence and evidence[-1].detail == "debt veto: headers_n=26"


def test_apply_leaves_unclaimed_results_untouched() -> None:
    geometry = GeometryText(headers=tuple(f"H{i}" for i in range(26)))
    empty = CompetitionResult(claims=(), contested=(), scores={})
    assert apply_debt_maturity_claim_vetoes([geometry], [empty]) == [empty]
