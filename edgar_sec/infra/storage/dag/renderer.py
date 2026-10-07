"""Cycle-tolerant ASCII swimlane and DAG graph renderer.

Renders multi-branch DAG topologies, detects cycles, and highlights bridge links.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True, slots=True)
class GraphNode:
    """Graph node representation for topological swimlane rendering."""

    snapshot_id: str
    kind: str
    parents: tuple[str, ...]
    checkpoint_anchor_id: str = ""
    bridge_links: tuple[str, ...] = ()
    labels: tuple[str, ...] = field(default_factory=tuple)


class DAGSwimlaneRenderer:
    """Renders topological DAG nodes with ASCII swimlanes and cycle tolerance."""

    def __init__(self, nodes: Sequence[GraphNode]) -> None:
        self.node_map = {n.snapshot_id: n for n in nodes}
        self.nodes = set(self.node_map.keys())
        self.adj: dict[str, list[str]] = defaultdict(list)
        self.parents: dict[str, list[str]] = defaultdict(list)

        for node in nodes:
            for p in node.parents:
                self.adj[node.snapshot_id].append(p)
                self.parents[p].append(node.snapshot_id)
                self.nodes.add(p)

    def compute_order(self) -> tuple[list[str], dict[str, list[str]]]:
        """Compute cycle-safe topological order and back-edge cycles."""
        in_degree = {n: len(self.parents[n]) for n in self.nodes}
        remaining_parents = {n: set(self.parents[n]) for n in self.nodes}
        queue = deque(sorted([n for n in self.nodes if in_degree[n] == 0]))
        order: list[str] = []
        cycle_back_edges: dict[str, list[str]] = defaultdict(list)
        visited: set[str] = set()

        while len(visited) < len(self.nodes):
            if not queue:
                unvisited = [n for n in self.nodes if n not in visited]
                chosen = min(
                    unvisited,
                    key=lambda n: (in_degree[n], -len(self.adj[n]), n),
                )
                for parent in list(remaining_parents[chosen]):
                    cycle_back_edges[chosen].append(parent)
                in_degree[chosen] = 0
                remaining_parents[chosen].clear()
                queue.append(chosen)

            curr = queue.popleft()
            if curr in visited:
                continue
            visited.add(curr)
            order.append(curr)

            for child in sorted(self.adj[curr]):
                if child in remaining_parents and curr in remaining_parents[child]:
                    remaining_parents[child].remove(curr)
                    in_degree[child] -= 1
                    if in_degree[child] == 0 and child not in visited:
                        queue.append(child)

        return order, cycle_back_edges

    def render(self) -> str:
        """Render DAG nodes into ASCII swimlanes with bridge link details."""
        order, cycle_back_edges = self.compute_order()
        lines: list[str] = []
        lanes: list[str] = []

        for node_id in order:
            indices = [i for i, target in enumerate(lanes) if target == node_id]
            if indices:
                active_idx = indices[0]
                lanes = [l for i, l in enumerate(lanes) if i not in indices[1:]]
            else:
                active_idx = len(lanes)
                lanes.append(node_id)

            track_repr: list[str] = []
            for i in range(len(lanes)):
                if i == active_idx:
                    track_repr.append("*" if node_id not in cycle_back_edges else "[!]")
                else:
                    track_repr.append("|")

            bar = " ".join(track_repr)
            node = self.node_map.get(node_id)
            kind = f"[{node.kind}]" if node else ""
            parents_str = (
                f"<- ({', '.join(node.parents)})" if node and node.parents else "(root)"
            )

            bridge_info = ""
            if node and node.checkpoint_anchor_id:
                if (
                    node.checkpoint_anchor_id not in node.parents
                    and node.checkpoint_anchor_id != node.snapshot_id
                ):
                    bridge_info = f"  ⚓ anchor: {node.checkpoint_anchor_id}"
            if node and node.bridge_links:
                bridge_info += f"  ⤹ bridge: {', '.join(node.bridge_links)}"

            label_info = f"  {' '.join(node.labels)}" if node and node.labels else ""
            cycle_info = ""
            if node_id in cycle_back_edges:
                cycle_info = (
                    f"  ⟲ CYCLE DETECTED (from: {', '.join(cycle_back_edges[node_id])})"
                )

            text = f"{bar:<10} {node_id:<16} {kind:<13} {parents_str:<22}{bridge_info}{label_info}{cycle_info}"
            lines.append(text.rstrip())

            children = sorted(self.adj[node_id])
            if children:
                lanes[active_idx] = children[0]
                for c in children[1:]:
                    lanes.append(c)
            else:
                lanes.pop(active_idx)

        return "\n".join(lines)


__all__ = [
    "DAGSwimlaneRenderer",
    "GraphNode",
]
