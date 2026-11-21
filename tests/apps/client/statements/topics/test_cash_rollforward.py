from __future__ import annotations

from edgar_sec.apps.client.core.facts import build_display_records
from edgar_sec.apps.client.statements.topics import build_cash_rollforward
from edgar_sec.engine.xbrl.schema.models import CalculationArc, XbrlFact
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.apps.client.statements.topics.topic_fixtures import _duration, _instant

_ROLLUP = "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
_CHANGE_INC = (
    "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
    "PeriodIncreaseDecreaseIncludingExchangeRateEffect"
)
_CHANGE_EXC = (
    "us-gaap:CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
    "PeriodIncreaseDecreaseExcludingExchangeRateEffect"
)
_FX = "us-gaap:EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"
_CARRYING = "us-gaap:CashAndCashEquivalentsAtCarryingValue"
_RESTRICTED = "us-gaap:RestrictedCash"


def _build(facts: list[XbrlFact], arcs: tuple[CalculationArc, ...] = ()):
    taxonomy = load_domain_taxonomy()
    records = build_display_records(facts, taxonomy)
    return build_cash_rollforward(facts, records, taxonomy, calculation_arcs=arcs)


def test_cash_rollforward_selects_identity_verified_total() -> None:
    """The compound total serves when beginning + change reproduces its end."""
    facts = [
        _instant(_ROLLUP, 1000.0, "2023-12-31"),
        _instant(_ROLLUP, 900.0, "2024-12-31"),
        _instant(_RESTRICTED, 80.0, "2023-12-31"),
        _instant(_RESTRICTED, 50.0, "2024-12-31"),
        _instant(_CARRYING, 850.0, "2024-12-31"),
        _duration(_CHANGE_INC, -100.0),
    ]
    graph = _build(facts)
    assert graph.total_concept == _ROLLUP
    assert graph.beginning == 1000.0
    assert graph.net_change == -100.0
    assert graph.end == 900.0
    assert graph.beginning_date == "2023-12-31"
    assert graph.end_date == "2024-12-31"
    assert graph.rollforward_verified is True
    assert graph.balance_sheet_total == 900.0
    assert graph.balance_sheet_verified is True


def test_cash_rollforward_calc_components_reconcile_end() -> None:
    """Calc children of the total reconcile it when they are filed lines."""
    facts = [
        _instant(_ROLLUP, 1000.0, "2023-12-31"),
        _instant(_ROLLUP, 900.0, "2024-12-31"),
        _instant("us-gaap:CashAndDueFromBanks", 300.0, "2024-12-31"),
        _instant("us-gaap:InterestBearingDepositsInBanks", 600.0, "2024-12-31"),
        _duration(_CHANGE_INC, -100.0),
    ]
    arcs = (
        CalculationArc(_ROLLUP, "us-gaap:CashAndDueFromBanks", 1.0),
        CalculationArc(_ROLLUP, "us-gaap:InterestBearingDepositsInBanks", 1.0),
    )
    graph = _build(facts, arcs)
    assert graph.balance_sheet_total == 900.0
    assert graph.balance_sheet_verified is True
    assert len(graph.components) == 2


def test_cash_rollforward_excluding_change_adds_fx_effect() -> None:
    """An excluding-FX change composes with the filed FX effect fact."""
    facts = [
        _instant(_ROLLUP, 1000.0, "2023-12-31"),
        _instant(_ROLLUP, 920.0, "2024-12-31"),
        _duration(_CHANGE_EXC, -100.0),
        _duration(_FX, 20.0),
    ]
    graph = _build(facts)
    assert graph.net_change == -80.0
    assert graph.rollforward_verified is True
    assert graph.balance_sheet_total is None
    assert graph.balance_sheet_verified is None


def test_cash_rollforward_reports_unverified_gap() -> None:
    """A total whose identity fails is served with its discrepancy shown."""
    facts = [
        _instant(_ROLLUP, 1000.0, "2023-12-31"),
        _instant(_ROLLUP, 900.0, "2024-12-31"),
        _duration(_CHANGE_INC, -50.0),
    ]
    graph = _build(facts)
    assert graph.end == 900.0
    assert graph.rollforward_verified is False
    assert graph.rollforward_discrepancy == -50.0
