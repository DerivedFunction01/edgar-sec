"""Grounded query specimens over the seed fixtures."""

from __future__ import annotations

from edgar_sec.engine.xbrl.solve.query import (
    FinancialQuery,
    QueryMode,
    QueryStatus,
)
from edgar_sec.engine.xbrl.solve.scoping import FactScope
from tests.support.corpus import bundle_text

from tests.engine.xbrl.solve.grounded_seed_support import _grounded_engine

from .conftest import load_seed_calculation_arcs, load_seed_facts


def test_bac_derivative_assets_precision_duplicate_reports_presented_value() -> None:
    result = _grounded_engine().execute(
        FinancialQuery(
            "us-gaap:DerivativeAssets",
            FactScope(
                accession="0000070858-25-000139",
                instant_date="2024-12-31",
                unit="USD",
            ),
        ),
        load_seed_facts("bac_2024_10k"),
        load_seed_calculation_arcs("bac_2024_10k"),
    )

    assert result.status == QueryStatus.REPORTED
    assert result.value == 40_948_000_000.0
    lines = bundle_text("bac_2024_10k").splitlines()
    assert "Derivative assets" in lines[4571]
    assert "40,948" in lines[4571]


def test_bac_net_income_pure_unit_scope_refuses_derivation() -> None:
    result = _grounded_engine().execute(
        FinancialQuery(
            "us-gaap:NetIncomeLoss",
            FactScope(
                accession="0000070858-25-000139",
                start_date="2024-01-01",
                end_date="2024-12-31",
                unit="pure",
            ),
            mode=QueryMode.VERIFY_DERIVATION,
        ),
        load_seed_facts("bac_2024_10k"),
        load_seed_calculation_arcs("bac_2024_10k"),
    )

    assert result.status == QueryStatus.UNAVAILABLE
    assert result.value is None


def test_bac_net_income_canonical_scope_verifies_by_comprehensive_income() -> None:
    result = _grounded_engine().execute(
        FinancialQuery(
            "us-gaap:NetIncomeLoss",
            FactScope(
                accession="0000070858-25-000139",
                start_date="2024-01-01",
                end_date="2024-12-31",
                unit="USD",
            ),
            mode=QueryMode.VERIFY_DERIVATION,
        ),
        load_seed_facts("bac_2024_10k"),
        load_seed_calculation_arcs("bac_2024_10k"),
    )

    assert result.status == QueryStatus.VERIFIED
    assert result.reported_fact is not None
    assert result.reported_fact.value == 27_132_000_000.0
    assert result.aggregate is not None
    assert result.aggregate.value == 27_132_000_000.0
    lines = bundle_text("bac_2024_10k").splitlines()
    assert "Net income" in lines[942]
    assert "27,132" in lines[942]


def test_msft_cash_duration_scope_refuses_derivation() -> None:
    result = _grounded_engine().execute(
        FinancialQuery(
            "us-gaap:CashAndCashEquivalentsAtCarryingValue",
            FactScope(
                accession="0000950170-24-087843",
                start_date="2024-04-01",
                end_date="2024-06-30",
                unit="USD",
            ),
            mode=QueryMode.VERIFY_DERIVATION,
        ),
        load_seed_facts("msft_2024_10k"),
        load_seed_calculation_arcs("msft_2024_10k"),
    )

    assert result.status == QueryStatus.UNAVAILABLE
    assert result.value is None


def test_msft_cash_canonical_instant_reports_without_derivation() -> None:
    result = _grounded_engine().execute(
        FinancialQuery(
            "us-gaap:CashAndCashEquivalentsAtCarryingValue",
            FactScope(
                accession="0000950170-24-087843",
                instant_date="2024-06-30",
                unit="USD",
            ),
            mode=QueryMode.VERIFY_DERIVATION,
        ),
        load_seed_facts("msft_2024_10k"),
        load_seed_calculation_arcs("msft_2024_10k"),
    )

    assert result.status == QueryStatus.REPORTED
    assert result.reported_fact is not None
    assert result.reported_fact.value == 18_315_000_000.0
    lines = bundle_text("msft_2024_10k").splitlines()
    assert "Cash and cash equivalents" in lines[1660]
    assert "18,315" in lines[1660]


def test_pld_cash_precision_duplicate_reports_presented_value() -> None:
    result = _grounded_engine().execute(
        FinancialQuery(
            "us-gaap:CashAndCashEquivalentsAtCarryingValue",
            FactScope(
                accession="0000950170-25-021272",
                instant_date="2024-12-31",
                unit="USD",
            ),
        ),
        load_seed_facts("pld_2024_10k"),
        load_seed_calculation_arcs("pld_2024_10k"),
    )

    assert result.status == QueryStatus.REPORTED
    assert result.value == 1_318_591_000.0
    lines = bundle_text("pld_2024_10k").splitlines()
    assert "Cash and cash equivalents" in lines[2259]
    assert "1,318,591" in lines[2259]


def test_aapl_loose_revenue_candidate_set_excludes_textblocks() -> None:
    result = _grounded_engine().execute(
        FinancialQuery(
            "Revenue",
            FactScope(
                accession="0000320193-24-000123",
                start_date="2023-10-01",
                end_date="2024-09-28",
            ),
        ),
        load_seed_facts("aapl_2024_10k"),
        load_seed_calculation_arcs("aapl_2024_10k"),
    )

    assert result.status == QueryStatus.REPORTED
    assert result.candidate_qnames == (
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
    )
    assert result.value == 391035000000.0
    assert result.tier == "near"
    assert not any("TextBlock" in qname for qname in result.candidate_qnames)


def test_msft_loose_revenue_candidate_set_excludes_textblock() -> None:
    result = _grounded_engine().execute(
        FinancialQuery(
            "Revenue",
            FactScope(
                accession="0000950170-24-087843",
                start_date="2023-07-01",
                end_date="2024-06-30",
            ),
        ),
        load_seed_facts("msft_2024_10k"),
        load_seed_calculation_arcs("msft_2024_10k"),
    )

    assert result.status == QueryStatus.REPORTED
    assert result.candidate_qnames == (
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
    )
    assert result.value == 245122000000.0


def test_bac_loose_revenue_candidate_set_excludes_textblock() -> None:
    result = _grounded_engine().execute(
        FinancialQuery(
            "Revenue",
            FactScope(
                accession="0000070858-25-000139",
                start_date="2024-01-01",
                end_date="2024-12-31",
            ),
        ),
        load_seed_facts("bac_2024_10k"),
        load_seed_calculation_arcs("bac_2024_10k"),
    )

    assert result.status == QueryStatus.REPORTED
    assert result.value == 101887000000.0
    assert result.candidate_qnames == ("us-gaap:Revenues",)


def test_pld_loose_revenue_candidate_set_excludes_textblock() -> None:
    result = _grounded_engine().execute(
        FinancialQuery(
            "Revenue",
            FactScope(
                accession="0000950170-25-021272",
                start_date="2024-01-01",
                end_date="2024-12-31",
            ),
        ),
        load_seed_facts("pld_2024_10k"),
        load_seed_calculation_arcs("pld_2024_10k"),
    )

    assert result.status == QueryStatus.REPORTED
    assert result.value == 8201610000.0
    assert result.candidate_qnames == ("us-gaap:Revenues",)


def test_bac_loose_derivative_liabilities_exclude_textblock() -> None:
    engine = _grounded_engine()
    facts = load_seed_facts("bac_2024_10k")
    arcs = load_seed_calculation_arcs("bac_2024_10k")

    unscoped = engine.execute(
        FinancialQuery(
            "DerivativeLiabilities",
            FactScope(accession="0000070858-25-000139"),
        ),
        facts,
        arcs,
    )
    assert unscoped.candidate_qnames == ("us-gaap:DerivativeLiabilities",)

    result = engine.execute(
        FinancialQuery(
            "DerivativeLiabilities",
            FactScope(
                accession="0000070858-25-000139",
                instant_date="2024-12-31",
                unit="USD",
            ),
        ),
        facts,
        arcs,
    )
    assert result.status == QueryStatus.REPORTED
    assert result.candidate_qnames == ("us-gaap:DerivativeLiabilities",)
    assert result.value == 39_353_000_000.0
    lines = bundle_text("bac_2024_10k").splitlines()
    assert "Derivative liabilities" in lines[4611]
    assert "39,353" in lines[4611]
