"""Tests for statement rendering exports."""

from edgar_sec.apps.client.rendering import statement_to_dataframe
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.solve.statement import (
    StatementEdge,
    StatementGraph,
    StatementNode,
)


def _node(qname: str) -> StatementNode:
    return StatementNode(
        concept_qname=qname, atom=Atom("H_TEST"), label=qname, facts=(), value=None
    )


def _graph(insertion_order: tuple[str, ...]) -> StatementGraph:
    nodes = {f"us-gaap:{name}": _node(f"us-gaap:{name}") for name in insertion_order}
    edges = (
        StatementEdge("us-gaap:root", "us-gaap:child_a", 1.0),
        StatementEdge("us-gaap:root", "us-gaap:child_b", 1.0),
        StatementEdge("us-gaap:child_a", "us-gaap:leaf", 1.0),
    )
    return StatementGraph("income", "us-gaap:root", nodes, edges, years=("2026",))


def test_statement_dataframe_order_ignores_node_insertion_order() -> None:
    """Row order is the table traversal, whatever order nodes were added."""
    forward = statement_to_dataframe(
        _graph(("root", "child_a", "child_b", "leaf")), include_yoy=False
    )
    scrambled = statement_to_dataframe(
        _graph(("leaf", "child_b", "root", "child_a")), include_yoy=False
    )
    expected = ["us-gaap:leaf", "us-gaap:child_a", "us-gaap:child_b", "us-gaap:root"]
    assert list(forward["concept"]) == expected
    assert list(scrambled["concept"]) == expected
