"""Cross-filing TTM: the window over item 18's stitched quarters."""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.apps.client.entity import Company
from edgar_sec.apps.client.facade import Edgar
from edgar_sec.apps.client.financials import XbrlFinancials
from edgar_sec.apps.client.financials_ttm_stitched import (
    stitched_quarter_legs,
    stitched_ttm,
)
from edgar_sec.apps.client.models import FilingsResult
from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.domain.submissions.models import EntityProfile
from edgar_sec.engine.xbrl.schema.models import FilingXbrl, LinkbaseBundle, XbrlFact
from edgar_sec.engine.xbrl.solve.assembly import StitchedSeries, assemble_series
from edgar_sec.engine.xbrl.solve.query import QueryStatus
from edgar_sec.engine.xbrl.solve.scoping import FilingRef
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy

_CIK = "1234"
_REVENUE = "us-gaap:Revenues"
_NET_INCOME = "us-gaap:NetIncomeLoss"
_CFO = "us-gaap:NetCashProvidedByUsedInOperatingActivities"
_CAPEX = "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment"
_SHARES = "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic"
_EPS_FILED = "us-gaap:EarningsPerShareBasic"

_Q1_24 = "0000001234-24-000011"
_Q2_24 = "0000001234-24-000012"
_Q3_24 = "0000001234-24-000013"
_K_24 = "0000001234-25-000014"
_RESTATE = "0000001234-25-000015"


def _ref(accession: str, form: str, period: str, filed: str) -> FilingRef:
    return FilingRef(
        accession=accession,
        cik=_CIK,
        form=form,
        report_period=period,
        filed_date=filed,
    )


def _fact(
    accession: str,
    qname: str,
    value: float,
    span: tuple[str, str],
    unit: str = "USD",
) -> XbrlFact:
    return XbrlFact(
        accession=AccessionNumber.from_any(accession),
        concept_qname=qname,
        value=value,
        unit=unit,
        period_type="duration",
        start_date=span[0],
        end_date=span[1],
    )


def _revenue_series() -> StitchedSeries:
    """Four filings whose pooled chains close TTM at Q3 2024; none alone does."""
    facts = [
        _fact(_Q1_24, _REVENUE, 100, ("2024-01-01", "2024-03-31")),
        _fact(_Q1_24, _REVENUE, 80, ("2023-01-01", "2023-03-31")),
        _fact(_Q2_24, _REVENUE, 250, ("2024-01-01", "2024-06-30")),
        _fact(_Q2_24, _REVENUE, 190, ("2023-01-01", "2023-06-30")),
        _fact(_Q3_24, _REVENUE, 420, ("2024-01-01", "2024-09-30")),
        _fact(_Q3_24, _REVENUE, 300, ("2023-01-01", "2023-09-30")),
        _fact(_K_24, _REVENUE, 620, ("2024-01-01", "2024-12-31")),
        _fact(_K_24, _REVENUE, 500, ("2023-01-01", "2023-12-31")),
    ]
    refs = [
        _ref(_Q1_24, "10-Q", "2024-03-31", "2024-04-30"),
        _ref(_Q2_24, "10-Q", "2024-06-30", "2024-07-31"),
        _ref(_Q3_24, "10-Q", "2024-09-30", "2024-10-31"),
        _ref(_K_24, "10-K", "2024-12-31", "2025-02-28"),
    ]
    return assemble_series(_CIK, facts, refs)


def _series_facts(series: StitchedSeries) -> list[XbrlFact]:
    """Rebuild filed facts from a series' winning values, for re-assembly."""
    return [
        _fact(
            value.source_accession,
            value.concept_qname,
            float(value.value),
            (value.start_date or "", value.end_date or ""),
            unit=value.unit or "USD",
        )
        for value in series.values
        if value.value is not None
    ]


def test_stitched_ttm_closes_where_no_single_filing_can() -> None:
    """The four-quarter sum closes across filings, legs naming their filings."""
    series = _revenue_series()
    result = stitched_ttm(series, "revenue", period_end="2024-09-30")
    assert result.status is QueryStatus.DERIVED
    assert result.value == 620
    assert result.route == "direct_four_quarter"
    assert len(result.legs) == 4
    by_span = {(leg.start, leg.end): leg for leg in result.legs}
    q1 = by_span[("2024-01-01", "2024-03-31")]
    assert q1.value == 100 and not q1.derived and q1.accession == _Q1_24
    q2 = by_span[("2024-04-01", "2024-06-30")]
    assert q2.value == 150 and q2.derived and q2.accession == _Q2_24
    assert [leg.accession for leg in q2.inputs] == [_Q1_24, _Q2_24]
    q4_prior = by_span[("2023-10-01", "2023-12-31")]
    assert q4_prior.value == 200 and q4_prior.derived
    assert [leg.accession for leg in q4_prior.inputs] == [_Q3_24, _K_24]


def test_the_same_window_is_unavailable_within_the_q3_filing_alone() -> None:
    """The Q3 10-Q alone carries no FY leg and no Q4 quarter: honest absence."""
    facts = [
        _fact(_Q3_24, _REVENUE, 420, ("2024-01-01", "2024-09-30")),
        _fact(_Q3_24, _REVENUE, 300, ("2023-01-01", "2023-09-30")),
    ]
    bundle = FilingXbrl(
        accession=AccessionNumber.from_any(_Q3_24),
        cik=Cik(1234),
        facts=tuple(facts),
        linkbases=LinkbaseBundle(),
    )
    fin: XbrlFinancials = Xbrl(bundle, load_domain_taxonomy()).financials
    result = fin.ttm("revenue", period_end="2024-09-30")
    assert result.value is None
    assert result.status is QueryStatus.UNAVAILABLE


def test_restated_quarter_wins_and_the_derived_chain_follows_it() -> None:
    """A later filing's restated Q1 replaces the original in leg and chain."""
    series = _revenue_series()
    facts = _series_facts(series) + [
        _fact(_RESTATE, _REVENUE, 105, ("2024-01-01", "2024-03-31"))
    ]
    refs = list(series.refs) + [_ref(_RESTATE, "10-Q/A", "2024-03-31", "2025-05-01")]
    restated = assemble_series(_CIK, facts, refs)
    legs = stitched_quarter_legs(restated, "revenue")
    quarters = {(leg.start, leg.end): leg for leg in legs.quarters}
    q1 = quarters[("2024-01-01", "2024-03-31")]
    assert q1.value == 105 and q1.accession == _RESTATE
    q2 = quarters[("2024-04-01", "2024-06-30")]
    assert q2.value == 145 and q2.derived
    result = stitched_ttm(restated, "revenue", period_end="2024-09-30")
    assert result.value == 620


def test_missing_quarter_is_named_across_filings() -> None:
    """A window whose fourth quarter no filing reports names that quarter."""
    facts = [
        _fact(_Q1_24, _REVENUE, 100, ("2024-01-01", "2024-03-31")),
        _fact(_Q2_24, _REVENUE, 250, ("2024-01-01", "2024-06-30")),
    ]
    refs = [
        _ref(_Q1_24, "10-Q", "2024-03-31", "2024-04-30"),
        _ref(_Q2_24, "10-Q", "2024-06-30", "2024-07-31"),
    ]
    series = assemble_series(_CIK, facts, refs)
    result = stitched_ttm(series, "revenue", period_end="2024-09-30")
    assert result.value is None
    assert result.status is QueryStatus.UNAVAILABLE
    assert result.missing == ("quarter ending 2024-09-30",)


def _eps_series() -> StitchedSeries:
    """Net income and share spans split across a 10-Q and the prior 10-K."""
    facts = [
        _fact(_Q3_24, _NET_INCOME, 210, ("2024-01-01", "2024-09-30")),
        _fact(_Q3_24, _NET_INCOME, 350, ("2023-01-01", "2023-09-30")),
        _fact(_K_24, _NET_INCOME, 500, ("2023-01-01", "2023-12-31")),
        _fact(_Q3_24, _SHARES, 110, ("2024-01-01", "2024-09-30"), unit="shares"),
        _fact(_Q3_24, _SHARES, 100, ("2023-01-01", "2023-09-30"), unit="shares"),
        _fact(_K_24, _SHARES, 100, ("2023-01-01", "2023-12-31"), unit="shares"),
        _fact(
            _Q3_24, _EPS_FILED, 1.91, ("2024-01-01", "2024-09-30"), unit="USD/shares"
        ),
        _fact(_K_24, _EPS_FILED, 5.0, ("2023-01-01", "2023-12-31"), unit="USD/shares"),
    ]
    refs = [
        _ref(_Q3_24, "10-Q", "2024-09-30", "2024-10-31"),
        _ref(_K_24, "10-K", "2024-12-31", "2025-02-28"),
    ]
    return assemble_series(_CIK, facts, refs)


def test_eps_ttm_is_the_ratio_and_shares_stay_day_weighted() -> None:
    """Filed EPS is never summed; share quarters difference by day counts."""
    series = _eps_series()
    shares = stitched_ttm(series, "weighted_shares_basic", period_end="2024-09-30")
    expected_shares = (100 * 364 + 110 * 273 - 100 * 272) / 365
    assert shares.value == pytest.approx(expected_shares)
    legs = stitched_quarter_legs(series, "weighted_shares_basic")
    quarters = {(leg.start, leg.end): leg for leg in legs.quarters}
    q4 = quarters[("2023-10-01", "2023-12-31")]
    assert q4.value == pytest.approx(100)
    eps = stitched_ttm(series, "eps_basic", period_end="2024-09-30")
    assert eps.status is QueryStatus.DERIVED
    assert eps.value == pytest.approx(round(360 / expected_shares, 4))
    with pytest.raises(ValueError):
        stitched_quarter_legs(series, "eps_basic")


def test_free_cash_flow_ttm_from_quarters_split_across_filings() -> None:
    """Each quarter's CFO and capex arrive in its own filing; FCF aligns them."""
    spans = [
        ("2024-01-01", "2024-03-31"),
        ("2024-04-01", "2024-06-30"),
        ("2024-07-01", "2024-09-30"),
        ("2024-10-01", "2024-12-31"),
    ]
    accessions = [_Q1_24, _Q2_24, _Q3_24, _K_24]
    facts = []
    refs = []
    for index, (span, accession) in enumerate(zip(spans, accessions)):
        facts.append(_fact(accession, _CFO, (index + 1) * 100, span))
        facts.append(_fact(accession, _CAPEX, (index + 1) * 10, span))
        form = "10-K" if index == 3 else "10-Q"
        refs.append(_ref(accession, form, span[1], f"2025-0{index + 1}-15"))
    series = assemble_series(_CIK, facts, refs)
    result = stitched_ttm(series, "free_cash_flow", period_end="2024-12-31")
    assert result.value == 900
    assert result.status is QueryStatus.DERIVED


def _break_series() -> StitchedSeries:
    """A filer whose fiscal year end moves from December to June."""
    facts = [
        _fact(_Q1_24, _REVENUE, 400, ("2022-01-01", "2022-12-31")),
        _fact(_Q2_24, _REVENUE, 500, ("2023-01-01", "2023-12-31")),
        _fact(_Q3_24, _REVENUE, 120, ("2024-07-01", "2024-09-30")),
        _fact(_K_24, _REVENUE, 130, ("2024-10-01", "2024-12-31")),
        _fact(_RESTATE, _REVENUE, 140, ("2025-01-01", "2025-03-31")),
        _fact("0000001234-25-000016", _REVENUE, 150, ("2025-04-01", "2025-06-30")),
        _fact("0000001234-25-000017", _REVENUE, 540, ("2024-07-01", "2025-06-30")),
    ]
    refs = [
        _ref(_Q1_24, "10-K", "2022-12-31", "2023-02-01"),
        _ref(_Q2_24, "10-K", "2023-12-31", "2024-02-01"),
        _ref(_Q3_24, "10-Q", "2024-09-30", "2024-11-01"),
        _ref(_K_24, "10-Q", "2024-12-31", "2025-02-01"),
        _ref(_RESTATE, "10-Q", "2025-03-31", "2025-05-01"),
        _ref("0000001234-25-000016", "10-Q", "2025-06-30", "2025-08-01"),
        _ref("0000001234-25-000017", "10-K", "2025-06-30", "2025-09-01"),
    ]
    return assemble_series(_CIK, facts, refs)


def test_fiscal_year_end_change_breaks_the_window() -> None:
    """The new calendar's TTM closes inside its segment; crossing is refused."""
    series = _break_series()
    assert len(series.breaks) == 1
    closed = stitched_ttm(series, "revenue", period_end="2025-06-30")
    assert closed.value == 540
    assert all(leg.end > "2023-12-31" for leg in closed.legs)
    refused = stitched_ttm(series, "revenue", period_end="2024-09-30")
    assert refused.value is None
    assert (
        refused.reason is not None and "series break after 2023-12-31" in refused.reason
    )


def test_instant_and_unknown_metrics_follow_the_filing_surface() -> None:
    """Instant metrics refuse as UNAVAILABLE; unknown metrics raise."""
    series = _revenue_series()
    instant = stitched_ttm(series, "total_assets")
    assert instant.value is None
    assert instant.reason is not None and "instant" in instant.reason
    with pytest.raises(ValueError):
        stitched_ttm(series, "no_such_metric")
    with pytest.raises(ValueError):
        stitched_quarter_legs(series, "total_assets")


def test_company_ttm_rides_the_stitched_selection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Company.ttm closes the identity route over two stubbed filings."""
    first = FilingAggregate(
        accession=AccessionNumber.from_any(_Q3_24),
        primary_cik=Cik(1234),
        ciks=(Cik(1234),),
        form="10-Q",
        filing_date="2024-10-31",
        report_date="2024-09-30",
    )
    second = FilingAggregate(
        accession=AccessionNumber.from_any(_K_24),
        primary_cik=Cik(1234),
        ciks=(Cik(1234),),
        form="10-K",
        filing_date="2025-02-28",
        report_date="2024-12-31",
    )
    parsed = {
        _Q3_24: FilingXbrl(
            accession=first.accession,
            cik=first.primary_cik,
            facts=(
                _fact(_Q3_24, _REVENUE, 420, ("2024-01-01", "2024-09-30")),
                _fact(_Q3_24, _REVENUE, 300, ("2023-01-01", "2023-09-30")),
            ),
            linkbases=LinkbaseBundle(),
        ),
        _K_24: FilingXbrl(
            accession=second.accession,
            cik=second.primary_cik,
            facts=(
                _fact(_K_24, _REVENUE, 620, ("2024-01-01", "2024-12-31")),
                _fact(_K_24, _REVENUE, 500, ("2023-01-01", "2023-12-31")),
            ),
            linkbases=LinkbaseBundle(),
        ),
    }
    monkeypatch.setattr(
        "edgar_sec.engine.xbrl.parsing.filing_parser.parse_filing_xbrl",
        lambda filing: parsed[filing.accession.value],
    )
    result = FilingsResult(
        run_id="test",
        plan_id="test",
        target_parquet_glob="",
        run_state_sqlite_path=tmp_path / "state.sqlite",
        artifacts_root=tmp_path,
        items=(first, second),
    )
    monkeypatch.setattr(Company, "filings", lambda self, **kwargs: result)
    company = Company(
        profile=EntityProfile(cik=Cik(1234), name="Stitch Co"),
        facade=Edgar(artifacts_root=tmp_path),
    )
    outcome = company.ttm("revenue", period_end="2024-09-30")
    assert outcome is not None
    assert outcome.value == 620
    bare = Company(profile=EntityProfile(cik=Cik(1234), name="Stitch Co"))
    assert bare.ttm("revenue") is None
