"""Tests proving per-firm query specimens: verification, guards, abstentions."""

from edgar_sec.engine.xbrl.solve.core.query import QueryMode, QueryStatus
from edgar_sec.engine.xbrl.solve.core.scoping import FactScope
from tests.apps.client.xbrl.xbrl_support import _MSFT_ACCESSION, _create_xbrl_facade


def test_xbrl_query_nvda_revenue_verify_surfaces_annual_conflict() -> None:
    """Verify NVDA revenue VERIFY reconciles via the gross-profit formula.

    The RPO percentage never answers; margin + cost solves to the headline.
    """
    xbrl = _create_xbrl_facade("nvda")

    result = xbrl.query("revenue", mode=QueryMode.VERIFY_DERIVATION, fiscal_year=2024)
    assert result.status == QueryStatus.VERIFIED
    assert result.reported_fact is not None
    assert result.reported_fact.value == 60922000000.0
    assert result.aggregate is not None
    assert result.aggregate.value == 60922000000.0
    assert result.value == 60922000000.0


def test_xbrl_query_aapl_assets_verify_resolves_at_fye_instant() -> None:
    """Verify AAPL Assets VERIFY returns the FYE VERIFIED, not a note-date DERIVED."""
    xbrl = _create_xbrl_facade("aapl")

    result = xbrl.query(
        "us-gaap:Assets", mode=QueryMode.VERIFY_DERIVATION, fiscal_year=2024
    )
    assert result.status == QueryStatus.VERIFIED
    assert result.value == 364980000000.0


def test_xbrl_query_aapl_derivative_assets_supertype_not_promoted() -> None:
    """Verify AAPL Derivative Assets is AMBIGUOUS: total Assets must not answer it."""
    xbrl = _create_xbrl_facade("aapl")

    for mode in (QueryMode.REPORTED_ONLY, QueryMode.VERIFY_DERIVATION):
        result = xbrl.query("Derivative Assets", mode=mode, fiscal_year=2024)
        assert result.status == QueryStatus.AMBIGUOUS
        assert result.value is None
        assert result.candidate_qnames == ("us-gaap:Assets",)
        assert result.tier == "near"
        assert len(result.equivalents) == 1
        assert result.equivalents[0].direction == "generalization"


def test_xbrl_query_aapl_derivative_liabilities_stays_ambiguous() -> None:
    """Verify AAPL Derivative Liabilities stays AMBIGUOUS over its equivalents."""
    xbrl = _create_xbrl_facade("aapl")

    result = xbrl.query("Derivative Liabilities", fiscal_year=2024)
    assert result.status == QueryStatus.AMBIGUOUS
    assert result.value is None
    assert len(result.candidate_qnames) == 7
    assert len(result.equivalents) == 7


def test_xbrl_query_gis_cash_verify_surfaces_fye_conflict() -> None:
    """Verify GIS Cash VERIFY reports the FYE fact; no derivation is claimed.

    The old -6,980M aggregate was a fabricated atom sum, not a derivation.
    """
    xbrl = _create_xbrl_facade("gis")

    result = xbrl.query(
        "us-gaap:CashAndCashEquivalentsAtCarryingValue",
        mode=QueryMode.VERIFY_DERIVATION,
        fiscal_year=2024,
    )
    assert result.status == QueryStatus.REPORTED
    assert result.reported_fact is not None
    assert result.reported_fact.value == 418000000.0
    assert result.aggregate is None
    assert result.value == 418000000.0


def test_xbrl_query_gis_gross_profit_fiscal_year_unavailable() -> None:
    """Verify GIS's quarterly-only GrossProfit is UNAVAILABLE for a fiscal-year query."""
    xbrl = _create_xbrl_facade("gis")

    result = xbrl.query("us-gaap:GrossProfit", fiscal_year=2024)
    assert result.status == QueryStatus.UNAVAILABLE
    assert result.value is None


def test_xbrl_query_bac_cash_verify_resolves_at_fye_instant() -> None:
    """Verify BAC Cash VERIFY abstains: the old -558,677M DERIVED was fabricated."""
    xbrl = _create_xbrl_facade("bac")

    result = xbrl.query(
        "us-gaap:CashAndCashEquivalentsAtCarryingValue",
        mode=QueryMode.VERIFY_DERIVATION,
        fiscal_year=2024,
    )
    assert result.status == QueryStatus.AMBIGUOUS
    assert result.value is None


def test_xbrl_query_msft_eps_diluted_resolves_at_annual_scope() -> None:
    """Verify diluted EPS still resolves REPORTED at the annual unitless scope."""
    xbrl = _create_xbrl_facade("msft")
    annual = xbrl.query(
        "us-gaap:EarningsPerShareDiluted",
        scope=FactScope(
            accession=_MSFT_ACCESSION, start_date="2023-07-01", end_date="2024-06-30"
        ),
    )

    result = xbrl.query("us-gaap:EarningsPerShareDiluted", fiscal_year=2024)
    assert result.status == QueryStatus.REPORTED
    assert result.value == annual.value == 11.8


def test_xbrl_query_bac_net_income_verify_surfaces_usd_conflict() -> None:
    """Verify BAC Net Income VERIFY reconciles via comprehensive income (G-pin)."""
    xbrl = _create_xbrl_facade("bac")

    result = xbrl.query(
        "us-gaap:NetIncomeLoss", mode=QueryMode.VERIFY_DERIVATION, fiscal_year=2024
    )
    assert result.status == QueryStatus.VERIFIED
    assert result.reported_fact is not None
    assert result.reported_fact.value == 27132000000.0
    assert result.aggregate is not None
    assert result.aggregate.value == 27132000000.0


def test_xbrl_query_gis_revenue_exact_carries_asc606_neighbour() -> None:
    """Verify GIS loose revenue is REPORTED exact with the ASC-606 neighbour visible (Q-B)."""
    xbrl = _create_xbrl_facade("gis")

    result = xbrl.query("revenue", fiscal_year=2024)
    assert result.status == QueryStatus.REPORTED
    assert result.value == 2037800000.0
    assert result.candidate_qnames == ("us-gaap:Revenues",)
    assert result.tier == "exact"
    by_qname = {item.qname: item for item in result.equivalents}
    assert by_qname["us-gaap:Revenues"].rule == "equality"
    neighbour = by_qname["us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"]
    assert neighbour.tier == "near"
    assert neighbour.rule == "subsumption"
    assert neighbour.direction == "specialization"


def test_xbrl_query_msft_revenue_guard_promotes_and_verify_reconciles() -> None:
    """Verify MSFT revenue guard-promotes the headline at NEAR tier; VERIFY
    reconciles it by solving Gross Profit's formula for the revenue term.
    """
    xbrl = _create_xbrl_facade("msft")

    result = xbrl.query("revenue", mode=QueryMode.REPORTED_ONLY, fiscal_year=2024)
    assert result.status == QueryStatus.REPORTED
    assert result.value == 245122000000.0
    assert result.tier == "near"
    best = result.equivalents[0]
    assert best.qname == ("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax")
    assert best.rule == "subsumption"
    assert best.direction == "specialization"

    verified = xbrl.query("revenue", mode=QueryMode.VERIFY_DERIVATION, fiscal_year=2024)
    assert verified.status == QueryStatus.VERIFIED
    assert verified.reported_fact is not None
    assert verified.reported_fact.value == 245122000000.0
    assert verified.aggregate is not None
    assert verified.aggregate.value == 245122000000.0
    assert verified.value == 245122000000.0


def test_xbrl_query_jnj_revenue_guard_promotion_surfaces_at_near_tier() -> None:
    """Verify JNJ revenue's guard promotion returns the headline, marked NEAR tier."""
    xbrl = _create_xbrl_facade("jnj")

    result = xbrl.query("revenue", fiscal_year=2024)
    assert result.status == QueryStatus.REPORTED
    assert result.value == 88821000000.0
    assert result.candidate_qnames == (
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
    )
    assert result.tier == "near"
    assert result.equivalents[0].direction == "specialization"
