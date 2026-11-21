from __future__ import annotations

from edgar_sec.apps.client.core.facts import build_display_records
from edgar_sec.apps.client.statements.rollforwards import build_level3_rollforward
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.apps.client.statements.topics.topic_fixtures import (
    _L3,
    _L3_AXIS,
    _L3_MEMBER,
    _L3_VALUE,
    _level3_fact,
)


def _build_level3(facts: list[XbrlFact], **kw: object):
    taxonomy = load_domain_taxonomy()
    records = build_display_records(facts, taxonomy)
    return build_level3_rollforward(facts, records, taxonomy, **kw)  # type: ignore[arg-type]


def test_level3_rollforward_verifies_asset_class() -> None:
    """Opening plus signed components reproduces the closing balance."""
    facts = [
        _level3_fact(_L3_VALUE, 1000.0, instant="2023-12-31"),
        _level3_fact(_L3_VALUE, 850.0, instant="2024-12-31"),
        _level3_fact(_L3 + "GainLossIncludedInEarnings1", 100.0),
        _level3_fact(_L3 + "GainLossIncludedInOtherComprehensiveIncomeLoss", -50.0),
        _level3_fact(_L3 + "Purchases", 200.0),
        _level3_fact(_L3 + "Sales", 300.0),
        _level3_fact(_L3 + "Issues", 10.0),
        _level3_fact(_L3 + "Settlements", 20.0),
        _level3_fact(_L3 + "TransfersIntoLevel3", 30.0),
        _level3_fact(_L3 + "TransfersOutOfLevel3", 120.0),
    ]
    graph = _build_level3(facts, axis_qname=_L3_AXIS, member_qname=_L3_MEMBER)
    assert graph.opening == 1000.0
    assert graph.closing == 850.0
    assert graph.total_gains == 50.0
    assert graph.transfers_in == 30.0
    assert graph.verified is True
    assert graph.discrepancy == 0.0
    assert graph.missing_components == ()
    assert graph.side == "asset"


_L3L = "us-gaap:FairValueMeasurementWithUnobservableInputsReconciliationRecurringBasisLiability"
_L3L_VALUE = (
    "us-gaap:FairValueMeasurementWithUnobservableInputsReconciliations"
    "RecurringBasisLiabilityValue"
)
_L3L_AXIS = "us-gaap:FairValueByLiabilityClassAxis"


def test_level3_rollforward_flips_gains_for_liability_class() -> None:
    """A filed liability loss increases the balance; the sign flips."""
    dims = {_L3L_AXIS: "x:DebtMember"}
    facts = [
        _level3_fact(_L3L_VALUE, 1000.0, dims, instant="2023-12-31"),
        _level3_fact(_L3L_VALUE, 1000.0, dims, instant="2024-12-31"),
        _level3_fact(_L3L + "GainLossIncludedInEarnings", -200.0, dims),
        _level3_fact(_L3L + "Issues", 100.0, dims),
        _level3_fact(_L3L + "Settlements", 300.0, dims),
    ]
    graph = _build_level3(facts, axis_qname=_L3L_AXIS, member_qname="x:DebtMember")
    assert graph.side == "liability"
    assert graph.verified is True
    assert graph.discrepancy == 0.0


def test_level3_rollforward_reports_gap_and_missing_components() -> None:
    """An unreconciled closing serves with its gap and missing roles named."""
    facts = [
        _level3_fact(_L3_VALUE, 1000.0, instant="2023-12-31"),
        _level3_fact(_L3_VALUE, 900.0, instant="2024-12-31"),
        _level3_fact(_L3 + "Purchases", 200.0),
    ]
    graph = _build_level3(facts, axis_qname=_L3_AXIS, member_qname=_L3_MEMBER)
    assert graph.verified is False
    assert graph.discrepancy == -300.0
    assert "gains" in graph.missing_components
    assert "sales" in graph.missing_components
    assert "transfers" in graph.missing_components


def test_level3_rollforward_counts_net_transfers_as_filed() -> None:
    """A single net transfers fact satisfies the transfers component."""
    facts = [
        _level3_fact(_L3_VALUE, 1000.0, instant="2023-12-31"),
        _level3_fact(_L3_VALUE, 1050.0, instant="2024-12-31"),
        _level3_fact(_L3 + "Purchases", 100.0),
        _level3_fact(_L3 + "TransfersNet", -50.0),
    ]
    graph = _build_level3(facts, axis_qname=_L3_AXIS, member_qname=_L3_MEMBER)
    assert graph.transfers_net == -50.0
    assert graph.verified is True
    assert "transfers" not in graph.missing_components
