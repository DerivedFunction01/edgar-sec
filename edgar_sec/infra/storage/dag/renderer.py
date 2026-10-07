"""Cycle-tolerant ASCII swimlane and DAG graph renderer.

Renders multi-branch DAG topologies, detects cycles, and highlights bridge links.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
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

    def render(
        self,
        *,
        offset: int = 0,
        limit: int | None = None,
        filter_text: str = "",
    ) -> str:
        """Render DAG nodes into ASCII swimlanes with bridge link details."""
        order, cycle_back_edges = self.compute_order()
        if filter_text:
            query = filter_text.strip().lower()
            filtered_order = [
                n_id
                for n_id in order
                if query in n_id.lower()
                or (
                    self.node_map.get(n_id)
                    and any(query in lbl.lower() for lbl in self.node_map[n_id].labels)
                )
                or (
                    self.node_map.get(n_id)
                    and query in self.node_map[n_id].checkpoint_anchor_id.lower()
                )
            ]
        else:
            filtered_order = order

        slice_end = (offset + limit) if limit is not None else None
        visible_order = (
            filtered_order[offset:slice_end]
            if (offset or limit is not None)
            else filtered_order
        )

        lines: list[str] = []
        lanes: list[str] = []

        for node_id in visible_order:
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


def build_graph_nodes(
    snapshots_root: Path | str,
    *,
    branch_name: str | None = None,
    all_heads: bool = False,
) -> list[GraphNode]:
    """Assemble graph nodes with branch and tag labels from root."""
    from .manifest import DAGNodeManifest
    from .publication import list_branches, read_pointer
    from .retention import discover_roots
    from .tags import list_tags
    from .traversal import walk_lineage

    root = Path(snapshots_root)
    all_branches = list_branches(root)
    branch_map: dict[str, list[str]] = {}
    for b in all_branches:
        b_ptr = read_pointer(root, branch_name=None if b == "current" else b)
        if b_ptr:
            s_id = str(b_ptr["snapshot_id"])
            lbl = "(HEAD -> current)" if b == "current" else f"(branch: {b})"
            branch_map.setdefault(s_id, []).append(lbl)

    tag_map: dict[str, list[str]] = {}
    for t in list_tags(root):
        tag_map.setdefault(str(t["snapshot_id"]), []).append(f"(tag: {t['tag']})")

    node_pool: dict[str, DAGNodeManifest] = {}
    if all_heads:
        heads = discover_roots(root)
        for head in heads:
            try:
                lin = walk_lineage(root, head)
                for node in lin.nodes:
                    node_pool[node.snapshot_id] = node
            except Exception:
                continue
    else:
        ptr = read_pointer(root, branch_name=branch_name)
        if ptr is not None:
            lin = walk_lineage(root, str(ptr["snapshot_id"]))
            for node in lin.nodes:
                node_pool[node.snapshot_id] = node

    graph_nodes: list[GraphNode] = []
    for node in node_pool.values():
        labels = branch_map.get(node.snapshot_id, []) + tag_map.get(
            node.snapshot_id, []
        )
        bridge_links: list[str] = []
        base_pin = node.metadata.get("base_snapshot_id")
        if base_pin:
            bridge_links.append(str(base_pin))
        graph_nodes.append(
            GraphNode(
                snapshot_id=node.snapshot_id,
                kind=node.kind,
                parents=tuple(p.snapshot_id for p in node.parents),
                checkpoint_anchor_id=node.checkpoint_anchor_id,
                bridge_links=tuple(bridge_links),
                labels=tuple(labels),
            )
        )
    return graph_nodes


__all__ = [
    "DAGSwimlaneRenderer",
    "GraphNode",
    "build_graph_nodes",
]
