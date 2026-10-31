"""Tests for identity-checked rollforward graph arithmetic."""

from edgar_sec.engine.xbrl.solve.rollforward_graphs import (
    CashRollforwardGraph,
    EquityComponentRollforward,
    EquityRollforwardGraph,
    Level3RollforwardGraph,
    PensionFundedStatusGraph,
    SegmentBreakdownGraph,
)


def test_moved_graph_families_still_construct() -> None:
    """The families extracted from statement.py keep their check math."""
    assert (
        CashRollforwardGraph(
            beginning=10.0, net_change=5.0, end=15.0
        ).rollforward_verified
        is True
    )
    assert (
        Level3RollforwardGraph(opening=10.0, closing=15.0, purchases=5.0).verified
        is True
    )
    assert SegmentBreakdownGraph(total=10.0).verified is None
    assert PensionFundedStatusGraph().funded_verified is None


def test_equity_component_rollforward_identity() -> None:
    """A component verifies when opening plus movements reaches closing."""
    comp = EquityComponentRollforward(
        member_qname="us-gaap:RetainedEarningsMember",
        opening=100.0,
        closing=130.0,
        movements={"net_income": 40.0, "dividends": -10.0},
        filed_net_change=30.0,
    )
    assert comp.computed_closing == 130.0
    assert comp.discrepancy == 0.0
    assert comp.verified is True
    assert comp.change_verified is True
    gapped = EquityComponentRollforward(
        member_qname="us-gaap:RetainedEarningsMember",
        opening=100.0,
        closing=125.0,
        movements={"net_income": 40.0},
    )
    assert gapped.verified is False
    assert gapped.discrepancy == -15.0
    assert gapped.change_verified is None


def test_equity_rollforward_graph_totals() -> None:
    """The total check sums only the antichain components' movements."""
    retained = EquityComponentRollforward(
        member_qname="us-gaap:RetainedEarningsMember",
        opening=100.0,
        closing=130.0,
        movements={"net_income": 30.0},
    )
    aoci = EquityComponentRollforward(
        member_qname="us-gaap:AccumulatedOtherComprehensiveIncomeMember",
        opening=50.0,
        closing=45.0,
        movements={"oci": -5.0},
    )
    sub = EquityComponentRollforward(
        member_qname="us-gaap:AccumulatedTranslationAdjustmentMember",
        opening=50.0,
        closing=45.0,
        movements={"oci": -5.0},
    )
    graph = EquityRollforwardGraph(
        opening=150.0,
        closing=175.0,
        components=(retained, aoci, sub),
        antichain_members=(retained.member_qname, aoci.member_qname),
    )
    assert graph.computed_closing == 175.0
    assert graph.verified is True
    assert graph.components_sum == 175.0
    assert graph.components_verified is True
    assert graph.component("us-gaap:RetainedEarningsMember") is retained
    assert graph.component("us-gaap:CommonStockMember") is None
