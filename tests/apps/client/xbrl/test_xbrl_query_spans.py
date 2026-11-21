"""Tests proving length-class span selection for fiscal-year queries."""

from edgar_sec.engine.xbrl.solve.core.query import QueryMode, QueryStatus
from edgar_sec.engine.xbrl.solve.core.scoping import FactScope
from tests.apps.client.xbrl.xbrl_support import (
    _ANNUAL,
    _MSFT_ACCESSION,
    _create_synthetic_xbrl,
    _create_xbrl_facade,
    _synthetic_fact,
)


def test_xbrl_query_length_class_selects_its_own_span() -> None:
    """Verify QUARTER and YTD_2Q requests answer from their own spans."""
    xbrl = _create_synthetic_xbrl(
        (
            _synthetic_fact(
                "us-gaap:Revenues", 100.0, start=_ANNUAL[0], end=_ANNUAL[1]
            ),
            _synthetic_fact(
                "us-gaap:Revenues", 30.0, start="2023-07-01", end="2023-09-30"
            ),
            _synthetic_fact(
                "us-gaap:Revenues", 55.0, start="2023-01-01", end="2023-06-30"
            ),
            _synthetic_fact("us-gaap:Assets", 500.0, instant="2023-12-31"),
        )
    )

    annual = xbrl.query("us-gaap:Revenues", fiscal_year=2023)
    assert annual.status == QueryStatus.REPORTED
    assert annual.value == 100.0
    quarter = xbrl.query("us-gaap:Revenues", fiscal_year=2023, length_class="QUARTER")
    assert quarter.status == QueryStatus.REPORTED
    assert quarter.value == 30.0
    ytd = xbrl.query("us-gaap:Revenues", fiscal_year=2023, length_class="YTD_2Q")
    assert ytd.status == QueryStatus.REPORTED
    assert ytd.value == 55.0
    instant = xbrl.query("us-gaap:Assets", fiscal_year=2023, length_class="INSTANT")
    assert instant.status == QueryStatus.REPORTED
    assert instant.value == 500.0


def test_xbrl_query_length_class_without_matching_span_is_unavailable() -> None:
    """Verify a length class the filing does not carry stays UNAVAILABLE."""
    xbrl = _create_synthetic_xbrl(
        (
            _synthetic_fact(
                "us-gaap:Revenues", 100.0, start=_ANNUAL[0], end=_ANNUAL[1]
            ),
            _synthetic_fact(
                "us-gaap:Revenues", 30.0, start="2023-07-01", end="2023-09-30"
            ),
        )
    )

    result = xbrl.query("us-gaap:Revenues", fiscal_year=2023, length_class="YTD_3Q")
    assert result.status == QueryStatus.UNAVAILABLE
    assert result.value is None
    instant = xbrl.query("us-gaap:Revenues", fiscal_year=2023, length_class="INSTANT")
    assert instant.status == QueryStatus.UNAVAILABLE
    assert instant.value is None


def test_xbrl_query_fiscal_year_instant_fact_cannot_answer_duration_term() -> None:
    """Verify an instant-scope REPORTED (RPO) does not override the annual tier."""
    xbrl = _create_synthetic_xbrl(
        (
            _synthetic_fact(
                "us-gaap:Revenues", 100.0, start=_ANNUAL[0], end=_ANNUAL[1]
            ),
            _synthetic_fact(
                "us-gaap:Revenues", 150.0, start=_ANNUAL[0], end=_ANNUAL[1]
            ),
            _synthetic_fact(
                "us-gaap:RevenueRemainingPerformanceObligation",
                999.0,
                instant="2023-12-31",
            ),
        )
    )

    result = xbrl.query("revenue", fiscal_year=2023)
    assert result.status == QueryStatus.CONFLICT
    assert result.value is None


def test_xbrl_query_pld_revenue_fiscal_year_reports_annual_headline() -> None:
    """Verify PLD loose revenue returns the annual headline, not the Q3 REPORTED."""
    xbrl = _create_xbrl_facade("pld")

    result = xbrl.query("revenue", fiscal_year=2024)
    assert result.status == QueryStatus.REPORTED
    assert result.value == 8201610000.0


def test_xbrl_query_msft_revenue_fiscal_year_ignores_rpo_instants() -> None:
    """Verify MSFT loose revenue answers the headline, never the RPO facts."""
    xbrl = _create_xbrl_facade("msft")

    result = xbrl.query("revenue", mode=QueryMode.REPORTED_ONLY, fiscal_year=2024)
    assert result.status == QueryStatus.REPORTED
    assert result.value == 245122000000.0
    assert result.candidate_qnames == (
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
    )

    verified = xbrl.query("revenue", mode=QueryMode.VERIFY_DERIVATION, fiscal_year=2024)
    assert verified.status == QueryStatus.VERIFIED
    assert verified.reported_fact is not None
    assert verified.reported_fact.concept_qname == (
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
    )
    assert verified.reported_fact.value == 245122000000.0
