"""Tests for the operator's scored name matching."""

from __future__ import annotations

from edgar_sec.apps.client.operator import operator_company_names


def test_scoring_exact_and_clear_winner() -> None:
    entries = [
        {"name": "Acme Anvils Inc", "cik": "111", "tickers": []},
        {"name": "Acme Rockets Inc", "cik": "222", "tickers": []},
    ]
    scored = operator_company_names.score_name_candidates("Acme Anvils", entries)
    assert scored[0]["cik"] == "111"
    assert scored[0]["score"] >= 0.98
    assert scored[0]["score"] - scored[1]["score"] >= 0.15
