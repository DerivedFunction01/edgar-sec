"""Tests proving dimension policy, panel queries, and composed queries."""

import pytest

from edgar_sec.apps.client.statements.comparison import panel_query
from edgar_sec.engine.xbrl.solve.query import QueryStatus
from tests.apps.client.xbrl.xbrl_support import (
    _ANNUAL,
    _RPO_CONCEPT,
    _create_synthetic_xbrl,
    _create_xbrl_facade,
    _synthetic_fact,
    _timed_rpo,
)


def test_xbrl_query_fiscal_year_annual_conflict_beats_quarterly_reported() -> None:
    """Verify a quarterly REPORTED never outranks the annual tier's CONFLICT."""
    xbrl = _create_synthetic_xbrl(
        (
            _synthetic_fact(
                "us-gaap:Revenues", 100.0, start=_ANNUAL[0], end=_ANNUAL[1]
            ),
            _synthetic_fact(
                "us-gaap:Revenues", 150.0, start=_ANNUAL[0], end=_ANNUAL[1]
            ),
            _synthetic_fact(
                "us-gaap:Revenues", 30.0, start="2023-07-01", end="2023-09-30"
            ),
        )
    )

    result = xbrl.query("revenue", fiscal_year=2023)
    assert result.status == QueryStatus.CONFLICT
    assert result.value is None


def test_xbrl_query_dimension_policy_answers_total_on_timing_axis() -> None:
    """Verify the horizon-totals policy answers a total filed only on a timing axis."""
    xbrl = _create_synthetic_xbrl(
        (
            _synthetic_fact("us-gaap:Assets", 999.0, instant="2023-12-31"),
            _timed_rpo(155.7, "2024-01-01"),
        )
    )

    default = xbrl.query(_RPO_CONCEPT, fiscal_year=2023)
    assert default.status == QueryStatus.UNAVAILABLE
    assert default.value is None

    opted = xbrl.query(
        _RPO_CONCEPT, fiscal_year=2023, dimension_policy="horizon_totals"
    )
    assert opted.status == QueryStatus.REPORTED
    assert opted.value == 155.7


def test_xbrl_query_dimension_policy_keeps_undimensioned_total() -> None:
    """Verify an undimensioned total outranks a dimensioned one under the policy."""
    xbrl = _create_synthetic_xbrl(
        (
            _synthetic_fact(_RPO_CONCEPT, 100.0, instant="2023-12-31"),
            _timed_rpo(150.0, "2024-01-01"),
        )
    )

    result = xbrl.query(
        _RPO_CONCEPT, fiscal_year=2023, dimension_policy="horizon_totals"
    )
    assert result.status == QueryStatus.REPORTED
    assert result.value == 100.0


def test_xbrl_query_dimension_policy_multiple_members_is_ambiguous() -> None:
    """Verify totals filed on several timing members are AMBIGUOUS, not a pick."""
    xbrl = _create_synthetic_xbrl(
        (
            _synthetic_fact("us-gaap:Assets", 999.0, instant="2023-12-31"),
            _timed_rpo(100.0, "2024-01-01"),
            _timed_rpo(150.0, "2025-01-01"),
        )
    )

    result = xbrl.query(
        _RPO_CONCEPT, fiscal_year=2023, dimension_policy="horizon_totals"
    )
    assert result.status == QueryStatus.AMBIGUOUS
    assert result.value is None


def test_xbrl_query_dimension_policy_amzn_specimen() -> None:
    """Verify Amazon's timing-axis RPO total answers only under the policy."""
    amzn = _create_xbrl_facade("amzn")

    default = amzn.query(_RPO_CONCEPT, fiscal_year=2023)
    assert default.status == QueryStatus.UNAVAILABLE

    opted = amzn.query(
        _RPO_CONCEPT, fiscal_year=2023, dimension_policy="horizon_totals"
    )
    assert opted.status == QueryStatus.REPORTED
    assert opted.value == 155_700_000_000.0

    msft = _create_xbrl_facade("msft")
    kept = msft.query(_RPO_CONCEPT, fiscal_year=2024, dimension_policy="horizon_totals")
    assert kept.status == QueryStatus.REPORTED
    assert kept.value == 275_000_000_000.0


def test_panel_query_fixed_year_all_answered() -> None:
    """Verify a fixed-year RPO panel answers every filer with a summed total."""
    facades = {firm: _create_xbrl_facade(firm) for firm in ("msft", "googl", "orcl")}
    panel = panel_query(facades, _RPO_CONCEPT, fiscal_year=2024)
    assert panel.missing == ()
    assert [row.value for row in panel.rows] == [
        275_000_000_000.0,
        93_200_000_000.0,
        97_900_000_000.0,
    ]
    assert panel.total == 466_100_000_000.0


def test_panel_query_latest_per_filer_with_policy() -> None:
    """Verify a latest-filings panel mixes vintages and answers Amazon's total."""
    facades = {
        firm: _create_xbrl_facade(firm) for firm in ("msft", "amzn", "googl", "orcl")
    }
    panel = panel_query(facades, _RPO_CONCEPT, dimension_policy="horizon_totals")
    assert panel.missing == ()
    values = {row.filer: row.value for row in panel.rows}
    assert values["amzn"] == 155_700_000_000.0
    assert panel.total == 621_800_000_000.0

    default = panel_query(facades, _RPO_CONCEPT)
    assert default.missing == ("amzn",)
    assert default.total == 466_100_000_000.0


def test_panel_query_names_unanswered_filers() -> None:
    """Verify a filer with no RPO fact is an explicit missing row, not a drop."""
    facades = {firm: _create_xbrl_facade(firm) for firm in ("msft", "aapl")}
    panel = panel_query(facades, _RPO_CONCEPT, dimension_policy="horizon_totals")
    assert panel.missing == ("aapl",)
    aapl_row = next(row for row in panel.rows if row.filer == "aapl")
    assert aapl_row.status == QueryStatus.UNAVAILABLE
    assert aapl_row.value is None


def test_compose_dimension_policy_propagates_to_operands() -> None:
    """Verify composed chains value Amazon's backlog only under the policy."""
    amzn = _create_xbrl_facade("amzn")
    terms = [("+", _RPO_CONCEPT), ("+", "us-gaap:ContractWithCustomerLiability")]

    default = amzn.compose(terms, fiscal_year=2023)
    assert default.value is None

    opted = amzn.compose(terms, fiscal_year=2023, dimension_policy="horizon_totals")
    assert opted.status == QueryStatus.REPORTED
    assert opted.value == 176_300_000_000.0


def test_xbrl_query_unknown_dimension_policy_raises() -> None:
    """Verify an unknown dimension policy string raises ValueError."""
    xbrl = _create_xbrl_facade("msft")
    with pytest.raises(ValueError, match="dimension policy"):
        xbrl.query("revenue", fiscal_year=2024, dimension_policy="everything")


def test_xbrl_query_fiscal_year_quarterly_only_concept_is_unavailable() -> None:
    """Verify a non-annual-only concept is UNAVAILABLE for a fiscal-year query."""
    xbrl = _create_synthetic_xbrl(
        (
            _synthetic_fact(
                "us-gaap:Revenues", 100.0, start=_ANNUAL[0], end=_ANNUAL[1]
            ),
            _synthetic_fact("us-gaap:Assets", 500.0, instant="2023-12-31"),
            _synthetic_fact(
                "us-gaap:GrossProfit", 40.0, start="2023-07-01", end="2023-09-30"
            ),
            _synthetic_fact(
                "us-gaap:GrossProfit", 35.0, start="2023-04-01", end="2023-06-30"
            ),
        )
    )

    result = xbrl.query("us-gaap:GrossProfit", fiscal_year=2023)
    assert result.status == QueryStatus.UNAVAILABLE
    assert result.value is None
