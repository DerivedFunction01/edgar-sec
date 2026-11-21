"""Cash rollforward specimens from the statement battery."""

from __future__ import annotations

from tests.apps.client.xbrl.battery.statement_battery_support import _battery, _facade


def test_cash_rollforward_reproduces_bac_rollup_specimen() -> None:
    """BAC rollforward verifies, tied to its two balance-sheet lines."""
    entry = _battery("bac-2024-cash-rollup")
    view = _facade(entry.accession).financials.cash_rollforward
    assert view.end == entry.expected_value
    assert view.beginning == 333_073_000_000.0
    assert view.net_change == -42_959_000_000.0
    assert view.rollforward_verified is True
    assert view.balance_sheet_verified is True
    assert view.balance_sheet_total == entry.expected_value
    assert {c.concept_qname for c in view.components} == {
        "us-gaap:CashAndDueFromBanks",
        "us-gaap:InterestBearingDepositsInBanks",
    }


def test_cash_rollforward_serves_jpm_rollup_without_calc_arcs() -> None:
    """JPM rollforward verifies; its balance-sheet tie reports the gap."""
    entry = _battery("jpm-cash")
    view = _facade(entry.accession).financials.cash_rollforward
    assert view.end == entry.expected_value
    assert view.beginning == 624_151_000_000.0
    assert view.net_change == -154_834_000_000.0
    assert view.rollforward_verified is True
    assert view.balance_sheet_total == 27_500_000_000.0
    assert view.balance_sheet_verified is False
    assert view.balance_sheet_discrepancy == 441_817_000_000.0


def test_cash_rollforward_reproduces_msft_specimen() -> None:
    """MSFT rollforward verifies, tied to its carrying-value line."""
    entry = _battery("msft-cash")
    view = _facade(entry.accession).financials.cash_rollforward
    assert view.end == entry.expected_value
    assert view.beginning == 34_704_000_000.0
    assert view.net_change == -16_389_000_000.0
    assert view.rollforward_verified is True
    assert view.balance_sheet_verified is True
