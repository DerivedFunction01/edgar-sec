from __future__ import annotations

from edgar_sec.apps.client.core.facts import build_display_records
from edgar_sec.apps.client.statements.rollforwards import build_fair_value_hierarchy
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.apps.client.statements.topics.topic_fixtures import (
    _L3,
    _L3_AXIS,
    _L3_MEMBER,
    _L3_VALUE,
    _fact,
    _instant,
    _level3_fact,
)

_FV_AXIS = "us-gaap:FairValueByFairValueHierarchyLevelAxis"
_FV_CONCEPT = "us-gaap:AssetsFairValueDisclosure"
_FV_L1 = "us-gaap:FairValueInputsLevel1Member"
_FV_L2 = "us-gaap:FairValueInputsLevel2Member"
_FV_L3 = "us-gaap:FairValueInputsLevel3Member"
_FV_NAV = "us-gaap:FairValueMeasuredAtNetAssetValuePerShareMember"
_FV_COMBINED = "x:FairValueInputsLevel1AndLevel2Member"


def _fv_fact(
    member: str, value: float, extra_dims: dict[str, str] | None = None
) -> XbrlFact:
    dims = {_FV_AXIS: member}
    dims.update(extra_dims or {})
    return _fact(
        _FV_CONCEPT,
        value,
        period_type="instant",
        instant_date="2024-12-31",
        dimensions=dims,
    )


def _hierarchy(facts: list[XbrlFact]):
    taxonomy = load_domain_taxonomy()
    records = build_display_records(facts, taxonomy)
    return build_fair_value_hierarchy(facts, records, taxonomy)


def test_fair_value_hierarchy_verifies_levels_against_total() -> None:
    """Filed level columns, NAV and combined included, reproduce the total."""
    facts = [
        _instant(_FV_CONCEPT, 1000.0, "2024-12-31"),
        _fv_fact(_FV_L1, 500.0),
        _fv_fact(_FV_L2, 300.0),
        _fv_fact(_FV_L3, 100.0),
        _fv_fact(_FV_NAV, 60.0),
        _fv_fact(_FV_COMBINED, 40.0),
    ]
    graph = _hierarchy(facts)
    assert len(graph.rows) == 1
    row = graph.rows[0]
    assert row.level1 == 500.0
    assert row.level2 == 300.0
    assert row.level3 == 100.0
    assert row.nav == 60.0
    assert row.levels[_FV_COMBINED] == 40.0
    assert row.levels_sum == row.total == 1000.0
    assert row.verified is True
    assert row.l3_tied is None


def test_fair_value_hierarchy_reports_unverified_gap() -> None:
    """A level split that misses the total serves unverified, not forced."""
    facts = [
        _instant(_FV_CONCEPT, 1000.0, "2024-12-31"),
        _fv_fact(_FV_L1, 500.0),
        _fv_fact(_FV_L2, 300.0),
    ]
    graph = _hierarchy(facts)
    row = graph.rows[0]
    assert row.verified is False
    assert row.discrepancy == 200.0


def test_fair_value_hierarchy_level3_ties_to_rollforward_class() -> None:
    """The Level-3 column ties to the rollforward class sharing its key."""
    facts = [
        _instant(_FV_CONCEPT, 9999.0, "2024-12-31"),
        _fv_fact(_FV_L3, 850.0, {_L3_AXIS: _L3_MEMBER}),
        _fv_fact(_FV_L3, 5.0, {_L3_AXIS: "x:OtherMember"}),
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
    graph = _hierarchy(facts)
    row = next(r for r in graph.rows if r.dimensions == ((_L3_AXIS, _L3_MEMBER),))
    assert row.level3 == 850.0
    assert row.l3_tied is True
    assert row.total is None
    assert row.verified is None
