from __future__ import annotations

from edgar_sec.apps.client.core.facts import build_display_records
from edgar_sec.apps.client.statements.equity_rollforward import build_equity_rollforward
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.apps.client.statements.topics.topic_fixtures import (
    _EQ_DOMAIN,
    _EQ_PARENT,
    _def_arcs,
    _fact,
)

_EQ_AXIS = "us-gaap:StatementEquityComponentsAxis"
_EQ_TOTAL = "us-gaap:StockholdersEquity"
_EQ_RE = "us-gaap:RetainedEarningsMember"
_EQ_AOCI = "us-gaap:AccumulatedOtherComprehensiveIncomeMember"
_EQ_TREASURY = "us-gaap:TreasuryStockCommonMember"
_EQ_COMMON = "us-gaap:CommonStockMember"


def _equity_fact(
    qname: str,
    value: float,
    member: str | None = None,
    instant: str | None = None,
) -> XbrlFact:
    dims = {_EQ_AXIS: member} if member else {}
    if instant is not None:
        return _fact(
            qname, value, period_type="instant", instant_date=instant, dimensions=dims
        )
    return _fact(
        qname,
        value,
        period_type="duration",
        start_date="2024-01-01",
        end_date="2024-12-31",
        dimensions=dims,
    )


def _build_equity(facts: list[XbrlFact], **kw: object):
    taxonomy = load_domain_taxonomy()
    records = build_display_records(facts, taxonomy)
    return build_equity_rollforward(facts, records, taxonomy, **kw)  # type: ignore[arg-type]


def test_equity_rollforward_verifies_components_and_total() -> None:
    """Components verify by identity; OCI decompositions never double count."""
    facts = [
        _equity_fact(_EQ_TOTAL, 1500.0, instant="2023-12-31"),
        _equity_fact(_EQ_TOTAL, 1750.0, instant="2024-12-31"),
        _equity_fact(_EQ_TOTAL, 1000.0, member=_EQ_RE, instant="2023-12-31"),
        _equity_fact(_EQ_TOTAL, 1300.0, member=_EQ_RE, instant="2024-12-31"),
        _equity_fact(_EQ_TOTAL, 500.0, member=_EQ_AOCI, instant="2023-12-31"),
        _equity_fact(_EQ_TOTAL, 450.0, member=_EQ_AOCI, instant="2024-12-31"),
        _equity_fact("us-gaap:NetIncomeLoss", 400.0, member=_EQ_RE),
        _equity_fact("us-gaap:DividendsCommonStockCash", 100.0, member=_EQ_RE),
        _equity_fact(
            "us-gaap:OtherComprehensiveIncomeLossNetOfTax", -50.0, member=_EQ_AOCI
        ),
        _equity_fact(
            "us-gaap:OtherComprehensiveIncomeLossBeforeReclassificationsNetOfTax",
            999.0,
            member=_EQ_AOCI,
        ),
        _equity_fact(
            "us-gaap:OtherComprehensiveIncomeLossTaxPortionAttributableToParent1",
            888.0,
            member=_EQ_AOCI,
        ),
    ]
    graph = _build_equity(facts)
    assert graph.balance_concept == _EQ_TOTAL
    assert graph.axis_qname == _EQ_AXIS
    assert graph.opening == 1500.0
    assert graph.closing == 1750.0
    assert graph.verified is True
    assert graph.components_verified is True
    assert set(graph.antichain_members) == {_EQ_RE, _EQ_AOCI}
    retained = graph.component(_EQ_RE)
    assert retained is not None
    assert retained.movements == {"net_income": 400.0, "dividends": -100.0}
    assert retained.verified is True
    aoci = graph.component(_EQ_AOCI)
    assert aoci is not None
    assert aoci.movements == {"oci": -50.0}
    assert aoci.verified is True
    assert graph.missing_components == ()


_EQ_TOTAL_INCL = (
    "us-gaap:StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"
)
_EQ_NCI = "us-gaap:NoncontrollingInterestMember"
_EQ_LOCATION = "us-gaap:BalanceSheetLocationAxis"
_BLK_PROFIT = "blk:ProfitLossExcludingRedeemableNoncontrollingInterests"


def test_equity_rollforward_consumes_attribution_slice_bottomline() -> None:
    """BLK shape: the statement lives on the including-NCI total, and its
    only axis-dimensioned profit row is an attribution-slice variant."""
    facts = [
        _fact(
            _EQ_TOTAL,
            25.0,
            period_type="instant",
            instant_date="2023-12-31",
            dimensions={_EQ_LOCATION: "us-gaap:FairValueInputsLevel1Member"},
        ),
        _fact(
            _EQ_TOTAL,
            30.0,
            period_type="instant",
            instant_date="2024-12-31",
            dimensions={_EQ_LOCATION: "us-gaap:FairValueInputsLevel1Member"},
        ),
        _equity_fact(_EQ_TOTAL_INCL, 1000.0, instant="2023-12-31"),
        _equity_fact(_EQ_TOTAL_INCL, 1600.0, instant="2024-12-31"),
        _equity_fact(_EQ_TOTAL_INCL, 800.0, member=_EQ_RE, instant="2023-12-31"),
        _equity_fact(_EQ_TOTAL_INCL, 1300.0, member=_EQ_RE, instant="2024-12-31"),
        _equity_fact(_EQ_TOTAL_INCL, 200.0, member=_EQ_NCI, instant="2023-12-31"),
        _equity_fact(_EQ_TOTAL_INCL, 300.0, member=_EQ_NCI, instant="2024-12-31"),
        _equity_fact(_BLK_PROFIT, 500.0, member=_EQ_RE),
        _equity_fact(_BLK_PROFIT, 100.0, member=_EQ_NCI),
    ]
    graph = _build_equity(facts)
    assert graph.balance_concept == _EQ_TOTAL_INCL
    assert graph.opening == 1000.0
    assert graph.closing == 1600.0
    assert graph.verified is True
    assert graph.components_verified is True
    retained = graph.component(_EQ_RE)
    assert retained is not None
    assert retained.movements == {"net_income": 500.0}
    assert retained.verified is True
    nci = graph.component(_EQ_NCI)
    assert nci is not None
    assert nci.movements == {"net_income": 100.0}
    assert nci.verified is True


def test_equity_rollforward_signs_treasury_acquisitions_on_treasury_only() -> None:
    """Acquired cost subtracts on the treasury member and is ignored elsewhere."""
    facts = [
        _equity_fact(_EQ_TOTAL, 900.0, instant="2023-12-31"),
        _equity_fact(_EQ_TOTAL, 750.0, instant="2024-12-31"),
        _equity_fact(_EQ_TOTAL, 100.0, member=_EQ_COMMON, instant="2023-12-31"),
        _equity_fact(_EQ_TOTAL, 100.0, member=_EQ_COMMON, instant="2024-12-31"),
        _equity_fact(_EQ_TOTAL, -200.0, member=_EQ_TREASURY, instant="2023-12-31"),
        _equity_fact(_EQ_TOTAL, -350.0, member=_EQ_TREASURY, instant="2024-12-31"),
        _equity_fact(_EQ_TOTAL, 1000.0, member=_EQ_RE, instant="2023-12-31"),
        _equity_fact(_EQ_TOTAL, 1000.0, member=_EQ_RE, instant="2024-12-31"),
        _equity_fact(
            "us-gaap:TreasuryStockValueAcquiredCostMethod", 200.0, member=_EQ_TREASURY
        ),
        _equity_fact(
            "us-gaap:TreasuryStockValueAcquiredCostMethod", 999.0, member=_EQ_COMMON
        ),
        _equity_fact("x:TreasuryStockValueReissued", 50.0, member=_EQ_TREASURY),
    ]
    graph = _build_equity(facts)
    treasury = graph.component(_EQ_TREASURY)
    assert treasury is not None
    assert treasury.movements == {
        "treasury_acquired": -200.0,
        "treasury_reissued": 50.0,
    }
    assert treasury.verified is True
    common = graph.component(_EQ_COMMON)
    assert common is not None
    assert common.movements == {}
    assert common.verified is True
    assert graph.verified is True


def test_equity_rollforward_reports_gap_and_missing_opening() -> None:
    """An unreconciled component serves with its gap; a missing leg is named."""
    facts = [
        _equity_fact(_EQ_TOTAL, 1000.0, instant="2024-12-31"),
        _equity_fact(_EQ_TOTAL, 1000.0, member=_EQ_RE, instant="2024-12-31"),
        _equity_fact("us-gaap:NetIncomeLoss", 400.0, member=_EQ_RE),
    ]
    graph = _build_equity(facts)
    retained = graph.component(_EQ_RE)
    assert retained is not None
    assert retained.opening is None
    assert retained.verified is None
    assert graph.verified is None
    assert "RetainedEarningsMember:opening_balance" in graph.missing_components
    facts.append(_equity_fact(_EQ_TOTAL, 900.0, member=_EQ_RE, instant="2023-12-31"))
    facts.append(_equity_fact(_EQ_TOTAL, 900.0, instant="2023-12-31"))
    graph = _build_equity(facts)
    retained = graph.component(_EQ_RE)
    assert retained is not None
    assert retained.computed_closing == 1300.0
    assert retained.verified is False
    assert retained.discrepancy == -300.0


def _equity_parent_facts() -> list[XbrlFact]:
    return [
        _equity_fact(_EQ_TOTAL, 1500.0, instant="2023-12-31"),
        _equity_fact(_EQ_TOTAL, 1750.0, instant="2024-12-31"),
        _equity_fact(_EQ_TOTAL, 1000.0, member=_EQ_RE, instant="2023-12-31"),
        _equity_fact(_EQ_TOTAL, 1300.0, member=_EQ_RE, instant="2024-12-31"),
        _equity_fact(_EQ_TOTAL, 500.0, member=_EQ_AOCI, instant="2023-12-31"),
        _equity_fact(_EQ_TOTAL, 450.0, member=_EQ_AOCI, instant="2024-12-31"),
        _equity_fact(_EQ_TOTAL, 1500.0, member=_EQ_PARENT, instant="2023-12-31"),
        _equity_fact(_EQ_TOTAL, 1750.0, member=_EQ_PARENT, instant="2024-12-31"),
        _equity_fact("us-gaap:NetIncomeLoss", 400.0, member=_EQ_RE),
        _equity_fact("us-gaap:DividendsCommonStockCash", 100.0, member=_EQ_RE),
        _equity_fact(
            "us-gaap:OtherComprehensiveIncomeLossNetOfTax", -50.0, member=_EQ_AOCI
        ),
    ]


def test_equity_antichain_from_frontier_excludes_subsumed() -> None:
    """A summed member subsumed by another summed member is excluded."""
    arcs = _def_arcs(
        _EQ_AXIS,
        _EQ_DOMAIN,
        [(_EQ_DOMAIN, _EQ_PARENT), (_EQ_PARENT, _EQ_RE), (_EQ_PARENT, _EQ_AOCI)],
    )
    graph = _build_equity(_equity_parent_facts(), definition_arcs=arcs)
    assert graph.antichain_members == (_EQ_PARENT,)
    assert graph.components_verified is True


def test_equity_frontier_keeps_declared_siblings_unlike_search() -> None:
    """Siblings declared flat stay in the antichain; the search drops one."""
    arcs = _def_arcs(
        _EQ_AXIS,
        _EQ_DOMAIN,
        [(_EQ_DOMAIN, _EQ_PARENT), (_EQ_DOMAIN, _EQ_RE), (_EQ_DOMAIN, _EQ_AOCI)],
    )
    graph = _build_equity(_equity_parent_facts(), definition_arcs=arcs)
    assert set(graph.antichain_members) == {_EQ_PARENT, _EQ_RE, _EQ_AOCI}
    assert graph.components_sum == 3500.0
    assert graph.components_verified is False
    fallback = _build_equity(_equity_parent_facts())
    assert fallback.antichain_members == (_EQ_PARENT,)
    assert fallback.components_verified is True
