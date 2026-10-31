"""Probe 10-Q period specimens: QTD and YTD answers stay distinguishable."""

from __future__ import annotations

import pytest

from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.discovery.cohort import canonical_probe_cohort_path
from edgar_sec.engine.xbrl.schema.models import FilingXbrl, LinkbaseBundle
from edgar_sec.engine.xbrl.solve.query import QueryStatus
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.pipelines.xbrl_review.bundles import load_filing, registry_filings

_FACADES: dict[str, Xbrl] = {}

# Specimen values are the filings' undimensioned facts in facts.parquet
# (Step 16 corroborates them against rendered filing text).
_AAPL = "0000320193-26-000020"
_CAT = "0000018230-26-000046"
_JPM = "0001628280-26-054343"
_MSFT = "0001193125-26-436133"


def _facade(accession: str) -> Xbrl:
    if accession not in _FACADES:
        seed = next(
            s
            for s in registry_filings(registry_path=canonical_probe_cohort_path())
            if str(s.accession) == accession
        )
        loaded = load_filing(seed, registry_path=canonical_probe_cohort_path())
        bundle = FilingXbrl(
            accession=AccessionNumber.from_any(accession),
            cik=Cik(int(seed.cik)),
            facts=loaded.facts,
            linkbases=LinkbaseBundle(
                calculation_arcs=loaded.calc_arcs,
                presentation_arcs=loaded.pres_arcs,
                declarations=tuple(loaded.declarations.values()),
            ),
        )
        _FACADES[accession] = Xbrl(bundle, load_domain_taxonomy())
    return _FACADES[accession]


@pytest.mark.parametrize(
    ("accession", "term", "qtd", "ytd_class", "ytd"),
    [
        (
            _AAPL,
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            109_417_000_000.0,
            "YTD_3Q",
            364_357_000_000.0,
        ),
        (_AAPL, "us-gaap:NetIncomeLoss", 29_789_000_000.0, "YTD_3Q", 101_464_000_000.0),
        (_AAPL, "us-gaap:EarningsPerShareDiluted", 2.02, "YTD_3Q", 6.88),
        (_CAT, "us-gaap:Revenues", 20_543_000_000.0, "YTD_2Q", 37_958_000_000.0),
        (_CAT, "us-gaap:ProfitLoss", 3_593_000_000.0, "YTD_2Q", 6_141_000_000.0),
        (_CAT, "us-gaap:EarningsPerShareDiluted", 7.77, "YTD_2Q", 13.23),
        (_JPM, "us-gaap:NetIncomeLoss", 21_155_000_000.0, "YTD_2Q", 37_649_000_000.0),
        (_JPM, "us-gaap:EarningsPerShareDiluted", 7.70, "YTD_2Q", 13.63),
    ],
)
def test_probe_query_distinguishes_qtd_from_ytd(
    accession: str, term: str, qtd: float, ytd_class: str, ytd: float
) -> None:
    """Verify each length class answers with its own span's filed value."""
    facade = _facade(accession)
    quarter = facade.query(term, fiscal_year=2026, length_class="QUARTER")
    assert quarter.status == QueryStatus.REPORTED
    assert quarter.value == qtd
    ytd_result = facade.query(term, fiscal_year=2026, length_class=ytd_class)
    assert ytd_result.status == QueryStatus.REPORTED
    assert ytd_result.value == ytd
    assert quarter.value != ytd_result.value


@pytest.mark.parametrize(
    ("accession", "term"),
    [
        (_AAPL, "us-gaap:NetIncomeLoss"),
        (_AAPL, "us-gaap:EarningsPerShareDiluted"),
        (_CAT, "us-gaap:Revenues"),
        (_JPM, "us-gaap:NetIncomeLoss"),
    ],
)
def test_probe_fiscal_year_query_without_annual_period_is_unavailable(
    accession: str, term: str
) -> None:
    """Verify a 10-Q's YTD span never masquerades as the annual tier."""
    result = _facade(accession).query(term, fiscal_year=2026)
    assert result.status == QueryStatus.UNAVAILABLE
    assert result.value is None


def test_probe_msft_quarter_only_answers_quarter_class() -> None:
    """Verify MSFT's Q1 10-Q serves QUARTER and refuses a YTD_3Q request."""
    facade = _facade(_MSFT)
    term = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    quarter = facade.query(term, fiscal_year=2026, length_class="QUARTER")
    assert quarter.status == QueryStatus.REPORTED
    assert quarter.value == 92_279_000_000.0
    ytd = facade.query(term, fiscal_year=2026, length_class="YTD_3Q")
    assert ytd.status == QueryStatus.UNAVAILABLE
    assert ytd.value is None


def test_probe_financials_series_are_length_class_keyed_by_span() -> None:
    """Verify AAPL series separate QTD from YTD and serve no annual series."""
    fin = _facade(_AAPL).financials
    assert fin.revenue_series == {}
    assert fin.net_income_series == {}
    assert fin._series("H_REVENUE", length_class="QUARTER") == {
        "2026": 109_417_000_000.0,
        "2025": 94_036_000_000.0,
    }
    assert fin._series("H_REVENUE", length_class="YTD_3Q") == {
        "2026": 364_357_000_000.0,
        "2025": 313_695_000_000.0,
    }
