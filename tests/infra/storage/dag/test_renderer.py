"""Tests for cycle-tolerant DAG swimlane renderer.
Verifies topological sorting, cycle detection, and bridge link rendering.
"""

from edgar_sec.infra.storage.dag.renderer import (
    DAGSwimlaneRenderer,
    GraphNode,
)


def test_renderer_linear_and_branching() -> None:
    """Verify swimlane ASCII rendering for linear and branching nodes."""
    nodes = [
        GraphNode("c0", "checkpoint", ()),
        GraphNode("d1", "delta", ("c0",), checkpoint_anchor_id="c0"),
        GraphNode(
            "d2",
            "delta",
            ("d1",),
            checkpoint_anchor_id="c0",
            labels=("(HEAD -> current)",),
        ),
    ]
    renderer = DAGSwimlaneRenderer(nodes)
    rendered = renderer.render()
    assert "*          d2" in rendered
    assert "anchor: c0" in rendered
    assert "(HEAD -> current)" in rendered
    assert "*          c0" in rendered


def test_renderer_cycle_tolerance() -> None:
    """Verify cycle detection and non-hanging recovery when loops exist."""
    nodes = [
        GraphNode("a", "delta", ("b",)),
        GraphNode("b", "delta", ("c",)),
        GraphNode("c", "delta", ("a",)),
    ]
    renderer = DAGSwimlaneRenderer(nodes)
    order, cycles = renderer.compute_order()
    assert len(order) == 3
    assert len(cycles) > 0
    rendered = renderer.render()
    assert "CYCLE DETECTED" in rendered
