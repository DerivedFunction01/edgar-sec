"""DAG operator inspection commands: status and lineage log."""

from __future__ import annotations

from pathlib import Path

from ..tags import list_tags
from ..working.publication import read_pointer
from ..working.renderer import DAGSwimlaneRenderer, build_graph_nodes
from ..working.traversal import walk_lineage
from .output import _emit


def cmd_status(
    snapshots_root: Path,
    *,
    branch_name: str | None = None,
    as_json: bool = False,
) -> int:
    """Report current pointer state, active branch, and lineage metrics."""
    ptr = read_pointer(snapshots_root, branch_name=branch_name)
    if ptr is None:
        target = f"branch '{branch_name}'" if branch_name else "default pointer"
        if as_json:
            _emit({"error": f"no active snapshot pointer for {target}"})
        else:
            print(f"No active snapshot pointer in {snapshots_root} ({target})")
        return 1
    tip_id = str(ptr["snapshot_id"])
    lineage = walk_lineage(snapshots_root, tip_id)
    tip = lineage.nodes[-1]
    tags = [
        t["tag"] for t in list_tags(snapshots_root) if t.get("snapshot_id") == tip_id
    ]
    info = {
        "snapshots_root": str(snapshots_root),
        "branch": branch_name or "current",
        "tip_snapshot_id": tip_id,
        "kind": tip.kind,
        "checkpoint_anchor_id": tip.checkpoint_anchor_id,
        "lineage_depth": lineage.depth,
        "ancestor_count": len(lineage.nodes),
        "relations": {k: len(v) for k, v in tip.relations.items()},
        "tags": tags,
        "created_at": tip.created_at,
    }
    if as_json:
        _emit(info)
    else:
        print(f"Branch: {branch_name or 'current'} -> Tip: {tip_id} ({tip.kind})")
        print(f"Anchor: {tip.checkpoint_anchor_id} | Depth: {lineage.depth}")
        if tags:
            print(f"Tags: {', '.join(tags)}")
        print(
            f"Relations: {', '.join(f'{k}:{len(v)}' for k, v in tip.relations.items())}"
        )
    return 0


def cmd_log(
    snapshots_root: Path,
    *,
    branch_name: str | None = None,
    limit: int | None = None,
    graph: bool = False,
    all_heads: bool = False,
    as_json: bool = False,
) -> int:
    """List topological node lineage from root to tip or render swimlanes."""
    if graph:
        return _render_graph_log(
            snapshots_root,
            branch_name=branch_name,
            all_heads=all_heads,
            limit=limit,
            as_json=as_json,
        )

    ptr = read_pointer(snapshots_root, branch_name=branch_name)
    if ptr is None:
        return 1
    lineage = walk_lineage(snapshots_root, str(ptr["snapshot_id"]))
    nodes = list(reversed(lineage.nodes))
    if limit is not None:
        nodes = nodes[:limit]
    records = [
        {
            "snapshot_id": n.snapshot_id,
            "kind": n.kind,
            "parents": [p.snapshot_id for p in n.parents],
            "checkpoint_anchor_id": n.checkpoint_anchor_id,
            "depth": n.lineage_depth,
            "created_at": n.created_at,
        }
        for n in nodes
    ]
    if as_json:
        _emit(records)
    else:
        for r in records:
            parents = ",".join(r["parents"]) or "none"
            anchor = (
                f" (anchor: {r['checkpoint_anchor_id']})"
                if r["checkpoint_anchor_id"]
                and r["checkpoint_anchor_id"] not in r["parents"]
                else ""
            )
            print(f"* [{r['kind']}] {r['snapshot_id']} (parents: {parents}){anchor}")
    return 0


def _render_graph_log(
    snapshots_root: Path,
    *,
    branch_name: str | None,
    all_heads: bool,
    limit: int | None,
    as_json: bool,
) -> int:
    """Render DAG topology via cycle-tolerant swimlane renderer."""
    graph_nodes = build_graph_nodes(
        snapshots_root, branch_name=branch_name, all_heads=all_heads
    )
    renderer = DAGSwimlaneRenderer(graph_nodes)
    if as_json:
        order, cycles = renderer.compute_order()
        _emit({"order": order, "cycles": cycles})
    else:
        print(renderer.render(limit=limit))
    return 0


__all__ = [
    "cmd_log",
    "cmd_status",
]
