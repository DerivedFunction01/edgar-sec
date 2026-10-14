"""Unit tests for AtomRelationGraph and lattice edge inheritance."""

from edgar_sec.engine.xbrl.atoms import Atom
from edgar_sec.engine.xbrl.relations import AtomRelation, AtomRelationGraph


def test_relation_graph_inherited_edge_lookup() -> None:
    """Verify subtypes inherit edges declared on general parent atoms."""
    general_rev = Atom("H_REVENUE")
    real_estate_rev = Atom("H_REVENUE", frozenset(["M_REAL_ESTATE"]))
    rpo = Atom("H_COMMITMENT", frozenset(["M_RPO_BACKLOG"]))

    edge = AtomRelation(
        edge_id="R_DUAL_REV_RPO",
        relation_type="DUAL_OF",
        source=general_rev,
        target=rpo,
    )
    graph = AtomRelationGraph((edge,))

    # RealEstateRevenueNet inherits the DUAL_OF edge because it is a subtype of general Revenues
    inherited = graph.find_inherited_edges(real_estate_rev, "DUAL_OF")
    assert len(inherited) == 1
    assert inherited[0].edge_id == "R_DUAL_REV_RPO"


def test_relation_graph_part_of_and_contra_targets() -> None:
    """Verify rollup targets and contra offset detection."""
    opex = Atom("H_EXPENSE", frozenset(["M_OPERATING"]))
    rd = Atom("H_EXPENSE", frozenset(["M_OPERATING", "M_RD"]))

    part_edge = AtomRelation(
        edge_id="R_PART_OPEX_RD",
        relation_type="PART_OF",
        source=rd,
        target=opex,
        algebraic_weight=1.0,
    )

    contra_edge = AtomRelation(
        edge_id="R_CONTRA_INCENTIVE",
        relation_type="CONTRA_OF",
        source=Atom("H_REVENUE", frozenset(["M_CONTRA_INCENTIVE"])),
        target=Atom("H_REVENUE"),
        algebraic_weight=-1.0,
    )

    graph = AtomRelationGraph((part_edge, contra_edge))

    targets = graph.find_parent_targets(rd)
    assert len(targets) == 1
    assert targets[0] == (opex, 1.0)

    incentive = Atom("H_REVENUE", frozenset(["M_CONTRA_INCENTIVE"]))
    contra_target = graph.find_contra_target(incentive)
    assert contra_target == (Atom("H_REVENUE"), -1.0)
