"""Tests proving fiscal-year query semantics against the engine oracle."""

import pytest

from edgar_sec.engine.xbrl.solve.query import QueryMode, QueryStatus
from edgar_sec.engine.xbrl.solve.scoping import FactScope
from tests.apps.client.xbrl.xbrl_support import (
    _MSFT_ACCESSION,
    _create_xbrl_facade,
    _oracle_query,
)


def test_xbrl_query_reported_duration_with_fiscal_year() -> None:
    """Verify fiscal-year duration queries match the engine oracle."""
    xbrl = _create_xbrl_facade("msft")
    oracle = _oracle_query(
        "Net Income",
        FactScope(
            accession=_MSFT_ACCESSION,
            start_date="2023-07-01",
            end_date="2024-06-30",
            unit="USD",
        ),
    )

    for term in ("Net Income", "us-gaap:NetIncomeLoss"):
        result = xbrl.query(term, fiscal_year=2024)
        assert result.status == QueryStatus.REPORTED
        assert result.value == oracle.value == 88136000000.0


def test_xbrl_query_reported_instant_with_fiscal_year() -> None:
    """Verify fiscal-year instant queries match the engine oracle."""
    xbrl = _create_xbrl_facade("msft")
    oracle = _oracle_query(
        "us-gaap:Assets",
        FactScope(accession=_MSFT_ACCESSION, instant_date="2024-06-30", unit="USD"),
    )

    result = xbrl.query("us-gaap:Assets", fiscal_year=2024)
    assert result.status == QueryStatus.REPORTED
    assert result.value == oracle.value == 512163000000.0


def test_xbrl_query_without_fiscal_year_is_ambiguous() -> None:
    """Verify a multi-context concept without a year stays ambiguous."""
    xbrl = _create_xbrl_facade("msft")

    result = xbrl.query("us-gaap:Assets")
    assert result.status == QueryStatus.AMBIGUOUS
    assert result.value is None


def test_xbrl_query_verify_derivation_matches_oracle() -> None:
    """Verify VERIFY_DERIVATION reconciles against the engine oracle."""
    xbrl = _create_xbrl_facade("msft")
    scope = FactScope(
        accession=_MSFT_ACCESSION,
        start_date="2023-07-01",
        end_date="2024-06-30",
        unit="USD",
    )
    oracle = _oracle_query("Net Income", scope, mode=QueryMode.VERIFY_DERIVATION)

    for mode in ("VERIFY_DERIVATION", QueryMode.VERIFY_DERIVATION):
        result = xbrl.query("Net Income", mode=mode, fiscal_year=2024)
        assert result.status == oracle.status == QueryStatus.VERIFIED
        assert result.value == oracle.value
        assert result.discrepancy == oracle.discrepancy == 0.0


def test_xbrl_query_invalid_mode_raises() -> None:
    """Verify unknown query modes raise instead of silently coercing."""
    xbrl = _create_xbrl_facade("msft")

    for bad_mode in ("SOLVED_FALLBACK", "bogus"):
        with pytest.raises(ValueError):
            xbrl.query("Net Income", mode=bad_mode, fiscal_year=2024)


def test_xbrl_query_explicit_scope_passthrough() -> None:
    """Verify an explicit scope is executed verbatim."""
    xbrl = _create_xbrl_facade("msft")
    scope = FactScope(accession=_MSFT_ACCESSION, instant_date="2024-06-30", unit="USD")
    oracle = _oracle_query("us-gaap:Assets", scope)

    result = xbrl.query("us-gaap:Assets", scope=scope)
    assert result.status == oracle.status == QueryStatus.REPORTED
    assert result.value == oracle.value


def test_xbrl_query_unknown_term_with_fiscal_year() -> None:
    """Verify unknown terms return UNAVAILABLE instead of raising."""
    xbrl = _create_xbrl_facade("msft")

    result = xbrl.query("UnrecognizedFinancialMeasure", fiscal_year=2024)
    assert result.status == QueryStatus.UNAVAILABLE
    assert result.value is None
