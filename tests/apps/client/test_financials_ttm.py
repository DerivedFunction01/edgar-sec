"""TTM serving: quarter legs, the statused window, and the getters."""

from __future__ import annotations

import pytest

from edgar_sec.apps.client.financials import XbrlFinancials
from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.schema.models import FilingXbrl, LinkbaseBundle, XbrlFact
from edgar_sec.engine.xbrl.solve.query import QueryStatus
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.support import bundle_dir

_ACCESSION = "0000000000-24-000001"
_REVENUE = "us-gaap:Revenues"
_NET_INCOME = "us-gaap:NetIncomeLoss"
_CFO = "us-gaap:NetCashProvidedByUsedInOperatingActivities"
_CAPEX = "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment"
_SHARES = "us-gaap:WeightedAverageNumberOfSharesOutstandingBasic"
_EPS_FILED = "us-gaap:EarningsPerShareBasic"


def _fact(
    qname: str,
    value: float,
    start: str,
    end: str,
    unit: str = "USD",
) -> XbrlFact:
    return XbrlFact(
        accession=AccessionNumber.from_any(_ACCESSION),
        concept_qname=qname,
        value=value,
        unit=unit,
        period_type="duration",
        start_date=start,
        end_date=end,
    )


def _financials(facts: list[XbrlFact]) -> XbrlFinancials:
    bundle = FilingXbrl(
        accession=AccessionNumber.from_any(_ACCESSION),
        cik=Cik(1),
        facts=tuple(facts),
        linkbases=LinkbaseBundle(),
    )
    return Xbrl(bundle, load_domain_taxonomy()).financials


def _two_year_revenue() -> XbrlFinancials:
    """A Q3 10-Q shape: prior FY chain complete, current chain to YTD_3Q."""
    return _financials(
        [
            _fact(_REVENUE, 200, "2023-01-01", "2023-03-31"),
            _fact(_REVENUE, 480, "2023-01-01", "2023-06-30"),
            _fact(_REVENUE, 700, "2023-01-01", "2023-09-30"),
            _fact(_REVENUE, 1000, "2023-01-01", "2023-12-31"),
            _fact(_REVENUE, 100, "2024-01-01", "2024-03-31"),
            _fact(_REVENUE, 250, "2024-01-01", "2024-06-30"),
            _fact(_REVENUE, 420, "2024-01-01", "2024-09-30"),
        ]
    )


def test_quarter_legs_derive_discrete_quarters_from_ytd_chains() -> None:
    """YTD differences become derived quarters with their inputs named."""
    legs = _two_year_revenue().quarter_legs("revenue")
    quarters = {(leg.start, leg.end): leg for leg in legs.quarters}
    q2 = quarters[("2024-04-01", "2024-06-30")]
    assert q2.value == 150
    assert q2.derived
    assert [(leg.start, leg.end) for leg in q2.inputs] == [
        ("2024-01-01", "2024-03-31"),
        ("2024-01-01", "2024-06-30"),
    ]
    q4 = quarters[("2023-10-01", "2023-12-31")]
    assert q4.value == 300
    assert q4.derived
    reported = {(leg.start, leg.end): leg for leg in legs.reported}
    assert reported[("2024-01-01", "2024-09-30")].accession == _ACCESSION
    assert legs.breaks == ()


def test_reported_quarter_wins_over_the_derived_difference() -> None:
    """A filed quarter for a span displaces the YTD difference for it."""
    fin = _financials(
        [
            _fact(_REVENUE, 100, "2024-01-01", "2024-03-31"),
            _fact(_REVENUE, 250, "2024-01-01", "2024-06-30"),
            _fact(_REVENUE, 151, "2024-04-01", "2024-06-30"),
        ]
    )
    quarters = {
        (leg.start, leg.end): leg for leg in fin.quarter_legs("revenue").quarters
    }
    assert quarters[("2024-04-01", "2024-06-30")].value == 151
    assert not quarters[("2024-04-01", "2024-06-30")].derived


def test_broken_chain_names_its_break_and_still_derives_q4() -> None:
    """A chain opening at YTD_3Q names the break; FY − YTD_3Q still closes."""
    fin = _financials(
        [
            _fact(_REVENUE, 420, "2024-01-01", "2024-09-30"),
            _fact(_REVENUE, 620, "2024-01-01", "2024-12-31"),
        ]
    )
    legs = fin.quarter_legs("revenue")
    assert any("opens at YTD_3Q" in text for text in legs.breaks)
    quarters = {(leg.start, leg.end): leg for leg in legs.quarters}
    assert quarters[("2024-10-01", "2024-12-31")].value == 200


def test_ttm_direct_and_identity_routes_agree() -> None:
    """Both routes close at Q3 2024 on the same value, DERIVED status."""
    result = _two_year_revenue().ttm("revenue")
    assert result.status is QueryStatus.DERIVED
    assert result.value == 720
    assert result.period_end == "2024-09-30"
    assert result.route == "direct_four_quarter"
    assert result.detail is not None and "fiscal_year_identity" in result.detail
    assert len(result.legs) == 4
    assert result.basis == "as-reported; no split adjustment"


def test_ttm_annual_span_close_on_a_10k_shape() -> None:
    """An annual leg at the period end is itself a closed TTM window."""
    fin = _financials(
        [
            _fact(_REVENUE, 1000, "2023-01-01", "2023-12-31"),
            _fact(_REVENUE, 1240, "2024-01-01", "2024-12-31"),
        ]
    )
    result = fin.revenue_ttm()
    assert result.value == 1240
    assert result.route == "annual_span"
    assert result.status is QueryStatus.DERIVED


def test_ttm_missing_quarter_is_an_unavailable_naming_it() -> None:
    """No route closes without the fourth quarter; the gap is named."""
    fin = _financials(
        [
            _fact(_REVENUE, 100, "2024-01-01", "2024-03-31"),
            _fact(_REVENUE, 250, "2024-01-01", "2024-06-30"),
        ]
    )
    result = fin.ttm("revenue", period_end="2024-09-30")
    assert result.value is None
    assert result.status is QueryStatus.UNAVAILABLE
    assert result.missing == ("quarter ending 2024-09-30",)


def test_ttm_route_disagreement_is_refused_not_picked() -> None:
    """An annual leg contradicting the four filed quarters closes nothing."""
    fin = _financials(
        [
            _fact(_REVENUE, 100, "2024-01-01", "2024-03-31"),
            _fact(_REVENUE, 150, "2024-04-01", "2024-06-30"),
            _fact(_REVENUE, 170, "2024-07-01", "2024-09-30"),
            _fact(_REVENUE, 200, "2024-10-01", "2024-12-31"),
            _fact(_REVENUE, 999, "2024-01-01", "2024-12-31"),
        ]
    )
    result = fin.ttm("revenue")
    assert result.value is None
    assert result.status is QueryStatus.UNAVAILABLE
    assert result.detail is not None and "annual_span=999" in result.detail


def test_ttm_refuses_instant_and_cumulative_shapes() -> None:
    """Instant metrics gain no TTM; cumulative spans are not legs."""
    fin = _financials([_fact(_REVENUE, 5000, "2022-01-01", "2024-12-31")])
    instant = fin.ttm("total_assets")
    assert instant.value is None
    assert instant.reason is not None and "instant" in instant.reason
    cumulative = fin.ttm("revenue")
    assert cumulative.value is None
    assert cumulative.status is QueryStatus.UNAVAILABLE


def test_eps_ttm_is_the_ratio_of_the_two_ttm_legs() -> None:
    """EPS TTM = TTM net income / TTM weighted shares; filed EPS unused."""
    fin = _financials(
        [
            _fact(_NET_INCOME, 500, "2023-01-01", "2023-12-31"),
            _fact(_NET_INCOME, 350, "2023-01-01", "2023-09-30"),
            _fact(_NET_INCOME, 210, "2024-01-01", "2024-09-30"),
            _fact(_SHARES, 100, "2023-01-01", "2023-12-31", unit="shares"),
            _fact(_SHARES, 100, "2023-01-01", "2023-09-30", unit="shares"),
            _fact(_SHARES, 110, "2024-01-01", "2024-09-30", unit="shares"),
            _fact(_EPS_FILED, 5.0, "2023-01-01", "2023-12-31", unit="USD/shares"),
            _fact(_EPS_FILED, 1.91, "2024-01-01", "2024-09-30", unit="USD/shares"),
        ]
    )
    shares = fin.weighted_shares_basic_ttm()
    expected_shares = (100 * 364 + 110 * 273 - 100 * 272) / 365
    assert shares.value == pytest.approx(expected_shares)
    eps = fin.eps_basic_ttm()
    assert eps.status is QueryStatus.DERIVED
    assert eps.value == pytest.approx(round(360 / expected_shares, 4))
    assert eps.detail is not None and "no split adjustment" in eps.detail


def test_capex_and_free_cash_flow_ttm_from_aligned_spans() -> None:
    """Capex sums its quarters; FCF differences aligned CFO/capex spans."""
    fin = _financials(
        [
            _fact(_CFO, 100, "2024-01-01", "2024-03-31"),
            _fact(_CFO, 200, "2024-04-01", "2024-06-30"),
            _fact(_CFO, 300, "2024-07-01", "2024-09-30"),
            _fact(_CFO, 300, "2024-10-01", "2024-12-31"),
            _fact(_CAPEX, 10, "2024-01-01", "2024-03-31"),
            _fact(_CAPEX, 20, "2024-04-01", "2024-06-30"),
            _fact(_CAPEX, 30, "2024-07-01", "2024-09-30"),
            _fact(_CAPEX, 40, "2024-10-01", "2024-12-31"),
        ]
    )
    assert fin.capex_ttm().value == 100
    fcf = fin.free_cash_flow_ttm()
    assert fcf.value == 800
    assert fcf.status is QueryStatus.DERIVED


def test_ttm_unknown_and_legless_metrics_raise_like_the_catalogue() -> None:
    """Unknown metrics raise; instant and per-share leg requests raise."""
    fin = _two_year_revenue()
    with pytest.raises(ValueError):
        fin.ttm("no_such_metric")
    with pytest.raises(ValueError):
        fin.quarter_legs("total_assets")
    with pytest.raises(ValueError):
        fin.quarter_legs("eps_basic")


def test_msft_bundle_revenue_ttm_closes_on_the_annual_span() -> None:
    """The seed 10-K's TTM is its filed FY2024 revenue, DERIVED status."""
    facade = Xbrl.from_bundle(bundle_dir("msft_2024_10k"), load_domain_taxonomy())
    result = facade.financials.revenue_ttm()
    assert result.value == 245_122_000_000
    assert result.period_end == "2024-06-30"
    assert result.route == "annual_span"
