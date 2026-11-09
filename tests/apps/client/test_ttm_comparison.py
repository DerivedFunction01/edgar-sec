"""Item 19 Step 5: company-facts TTM as a comparison surface only."""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.apps.client.companyfacts import (
    AGREE,
    DIVERGE,
    FACTS_ONLY,
    PARSED_ONLY,
    CompanyFact,
    CompanyFacts,
)
from edgar_sec.apps.client.financials_ttm import TtmResult
from edgar_sec.apps.client.ttm_comparison import (
    compare_ttm,
    facts_eps_ttm,
    facts_quarter_legs,
    facts_ttm,
    facts_ttm_from_store,
)
from edgar_sec.engine.xbrl.solve.query import QueryStatus
from edgar_sec.pipelines.metadata_sync.facts_store import open_facts_store

_CIK = 1234
_REVENUE = ("us-gaap", "Revenues")
_SHARES = ("us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic")
_INCOME = ("us-gaap", "NetIncomeLoss")


def _point(
    tag: str,
    value: float,
    span: tuple[str, str] | None,
    *,
    taxonomy: str = "us-gaap",
    unit: str = "USD",
    accession: str = "0000001234-25-000010",
    filed: str = "2025-02-28",
) -> CompanyFact:
    return CompanyFact(
        taxonomy=taxonomy,
        tag=tag,
        unit=unit,
        value=value,
        start=span[0] if span else "",
        end=span[1] if span else "",
        accession=accession,
        form="10-K",
        filed=filed,
        fiscal_year=2024,
        fiscal_period="FY",
        frame="",
    )


def _revenue_facts(ytd3_24: float = 420) -> CompanyFacts:
    """Revenue points closing TTM 620 at 2024-09-30 by the identity route."""
    points = [
        _point("Revenues", ytd3_24, ("2024-01-01", "2024-09-30")),
        _point("Revenues", 300, ("2023-01-01", "2023-09-30")),
        _point("Revenues", 620, ("2024-01-01", "2024-12-31")),
        _point("Revenues", 500, ("2023-01-01", "2023-12-31")),
    ]
    return CompanyFacts(cik=_CIK, entity_name="Facts Co", facts=tuple(points))


def _xbrl_result(value: float | None, period_end: str | None = "2024-09-30"):
    return TtmResult(
        metric="revenue",
        value=value,
        status=QueryStatus.DERIVED if value is not None else QueryStatus.UNAVAILABLE,
        period_end=period_end if value is not None else None,
        legs=(),
        route="fiscal_year_identity" if value is not None else None,
        reason=None if value is not None else "no window",
    )


def test_facts_ttm_closes_by_the_identity_route() -> None:
    """The facts side reproduces the XBRL window arithmetic exactly."""
    result = facts_ttm(_revenue_facts(), *_REVENUE, period_end="2024-09-30")
    assert result.value == 620
    assert result.status is QueryStatus.DERIVED
    assert result.route == "fiscal_year_identity"
    legs = facts_quarter_legs(_revenue_facts(), *_REVENUE)
    assert len(legs.reported) == 4


def test_compare_ttm_agrees_when_both_surfaces_close() -> None:
    """Equal values at the same closing end agree."""
    facts_result = facts_ttm(_revenue_facts(), *_REVENUE, period_end="2024-09-30")
    row = compare_ttm(
        cik=_CIK, metric="revenue", xbrl=_xbrl_result(620), facts=facts_result
    )
    assert row is not None
    assert row.outcome == AGREE


def test_compare_ttm_diverges_on_value_or_end() -> None:
    """A shifted facts value, or a different closing end, diverges."""
    facts_result = facts_ttm(
        _revenue_facts(ytd3_24=421), *_REVENUE, period_end="2024-09-30"
    )
    row = compare_ttm(
        cik=_CIK, metric="revenue", xbrl=_xbrl_result(620), facts=facts_result
    )
    assert row is not None and row.outcome == DIVERGE
    other_end = facts_ttm(_revenue_facts(), *_REVENUE)
    row = compare_ttm(
        cik=_CIK, metric="revenue", xbrl=_xbrl_result(620), facts=other_end
    )
    assert row is not None and row.outcome == DIVERGE


def test_compare_ttm_single_surface_outcomes() -> None:
    """One-sided results classify; two-sided absence yields no row."""
    facts_result = facts_ttm(_revenue_facts(), *_REVENUE, period_end="2024-09-30")
    row = compare_ttm(
        cik=_CIK, metric="revenue", xbrl=_xbrl_result(None), facts=facts_result
    )
    assert row is not None and row.outcome == FACTS_ONLY
    empty = CompanyFacts(cik=_CIK, entity_name="Facts Co", facts=())
    absent = facts_ttm(empty, *_REVENUE)
    assert absent.value is None and absent.status is QueryStatus.UNAVAILABLE
    row = compare_ttm(cik=_CIK, metric="revenue", xbrl=_xbrl_result(620), facts=absent)
    assert row is not None and row.outcome == PARSED_ONLY
    assert (
        compare_ttm(cik=_CIK, metric="revenue", xbrl=_xbrl_result(None), facts=absent)
        is None
    )


def test_facts_eps_is_a_ratio_of_two_ttms() -> None:
    """Filed EPS points never enter; the ratio of the two TTMs serves."""
    points = [
        _point("NetIncomeLoss", 350, ("2023-01-01", "2023-09-30")),
        _point("NetIncomeLoss", 500, ("2023-01-01", "2023-12-31")),
        _point("NetIncomeLoss", 210, ("2024-01-01", "2024-09-30")),
        _point(
            "WeightedAverageNumberOfSharesOutstandingBasic",
            100,
            ("2023-01-01", "2023-09-30"),
            unit="shares",
        ),
        _point(
            "WeightedAverageNumberOfSharesOutstandingBasic",
            100,
            ("2023-01-01", "2023-12-31"),
            unit="shares",
        ),
        _point(
            "WeightedAverageNumberOfSharesOutstandingBasic",
            110,
            ("2024-01-01", "2024-09-30"),
            unit="shares",
        ),
        _point(
            "EarningsPerShareBasic",
            99.0,
            ("2024-01-01", "2024-09-30"),
            unit="USD/shares",
        ),
    ]
    facts = CompanyFacts(cik=_CIK, entity_name="Facts Co", facts=tuple(points))
    result = facts_eps_ttm(
        facts, income=_INCOME, shares=_SHARES, period_end="2024-09-30"
    )
    expected = (100 * 364 + 110 * 273 - 100 * 272) / 365
    assert result.value == pytest.approx(round(360 / expected, 4))
    assert result.route == "eps_ratio"


def test_facts_ttm_from_store_reads_the_bulk_store(tmp_path: Path) -> None:
    """The store leg converts StoredFact rows into the same comparison."""
    store = tmp_path / "facts.duckdb"
    con = open_facts_store(store)
    rows = [
        (420, ("2024-01-01", "2024-09-30")),
        (300, ("2023-01-01", "2023-09-30")),
        (620, ("2024-01-01", "2024-12-31")),
        (500, ("2023-01-01", "2023-12-31")),
    ]
    for value, (start, end) in rows:
        con.execute(
            "INSERT INTO company_facts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?,"
            " ?, ?, ?, ?, ?, ?)",
            [
                _CIK,
                "us-gaap",
                "Revenues",
                "USD",
                start,
                end,
                "0000001234-25-000010",
                "10-K",
                "2025-02-28",
                2024,
                "FY",
                "",
                float(value),
                "sha",
                0,
            ],
        )
    con.close()
    result = facts_ttm_from_store(store, _CIK, *_REVENUE, period_end="2024-09-30")
    assert result.value == 620
