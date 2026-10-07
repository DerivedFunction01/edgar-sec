"""Unified command-line interface for the snapshot DAG engine.

Provides inspection, lineage traversal, checkout, diagnostics, and garbage collection.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .doctor import audit_graph
from .publication import checkout_tip, read_pointer
from .retention import analyze_retention, purge_unreferenced
from .traversal import walk_lineage


def _emit(data: dict[str, Any] | list[Any]) -> None:
    print(json.dumps(data, indent=2))


def cmd_status(snapshots_root: Path, *, as_json: bool = False) -> int:
    """Report current pointer state and lineage metrics."""
    ptr = read_pointer(snapshots_root)
    if ptr is None:
        if as_json:
            _emit({"error": "no active snapshot pointer"})
        else:
            print(f"No active snapshot pointer in {snapshots_root}")
        return 1
    tip_id = str(ptr["snapshot_id"])
    lineage = walk_lineage(snapshots_root, tip_id)
    tip = lineage.nodes[-1]
    info = {
        "snapshots_root": str(snapshots_root),
        "tip_snapshot_id": tip_id,
        "kind": tip.kind,
        "checkpoint_anchor_id": tip.checkpoint_anchor_id,
        "lineage_depth": lineage.depth,
        "ancestor_count": len(lineage.nodes),
        "relations": {k: len(v) for k, v in tip.relations.items()},
        "created_at": tip.created_at,
    }
    if as_json:
        _emit(info)
    else:
        print(f"Tip: {tip_id} ({tip.kind})")
        print(f"Anchor: {tip.checkpoint_anchor_id} | Depth: {lineage.depth}")
        print(
            f"Relations: {', '.join(f'{k}:{len(v)}' for k, v in tip.relations.items())}"
        )
    return 0


def cmd_log(
    snapshots_root: Path,
    *,
    limit: int | None = None,
    as_json: bool = False,
) -> int:
    """List topological node lineage from root to tip."""
    ptr = read_pointer(snapshots_root)
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
            print(f"* [{r['kind']}] {r['snapshot_id']} (parents: {parents})")
    return 0


def cmd_checkout(snapshots_root: Path, snapshot_id: str) -> int:
    """Atomically swing the current pointer to a target snapshot."""
    checkout_tip(snapshots_root, snapshot_id)
    print(f"Checked out tip: {snapshot_id}")
    return 0


def cmd_doctor(
    snapshots_root: Path,
    *,
    as_json: bool = False,
) -> int:
    """Run diagnostics on lineage and repository integrity."""
    audit = audit_graph(snapshots_root)
    report = {
        "snapshots_root": str(snapshots_root),
        "healthy": audit.is_healthy,
        "error_count": len(audit.errors),
        "warning_count": len(audit.warnings),
        "errors": list(audit.errors),
        "warnings": list(audit.warnings),
        "active_tips": list(audit.active_tips),
    }
    if as_json:
        _emit(report)
    else:
        status = "HEALTHY" if audit.is_healthy else f"ISSUES ({len(audit.errors)})"
        print(f"Repository {snapshots_root}: {status}")
        for err in audit.errors:
            print(f"  ERROR: {err}")
        for warn in audit.warnings:
            print(f"  WARN: {warn}")
    return 0 if audit.is_healthy else 1


def cmd_gc(
    snapshots_root: Path,
    *,
    dry_run: bool = False,
    as_json: bool = False,
) -> int:
    """Collect unreferenced snapshot nodes and orphan parts."""
    report = analyze_retention(snapshots_root)
    purged = purge_unreferenced(snapshots_root, report, dry_run=dry_run)
    payload = {
        "prunable_snapshots": list(report.prunable_snapshots),
        "purged_snapshots": purged,
        "reclaimed_bytes": report.prunable_byte_size,
        "dry_run": dry_run,
    }
    if as_json:
        _emit(payload)
    else:
        print(f"Reclaimed {report.prunable_byte_size} bytes")
        print(f"Purged snapshots: {len(purged)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser for DAG operations."""
    parser = argparse.ArgumentParser(prog="dag", description="Snapshot DAG CLI")
    parser.add_argument(
        "--root", type=Path, default=Path("."), help="Snapshots directory"
    )
    parser.add_argument("--json", action="store_true", help="Format output as JSON")
    sub = parser.add_subparsers(dest="subcommand", required=True)

    sub.add_parser("status", help="Show current snapshot status")
    log_p = sub.add_parser("log", help="Display lineage history")
    log_p.add_argument("-n", "--limit", type=int, default=None, help="Max entries")
    co_p = sub.add_parser("checkout", help="Switch current pointer")
    co_p.add_argument("snapshot_id", help="Target snapshot ID")
    sub.add_parser("doctor", help="Run integrity checks")
    gc_p = sub.add_parser("gc", help="Collect unreferenced snapshots and parts")
    gc_p.add_argument("--dry-run", action="store_true", help="Preview deletions")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for DAG CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)
    root = args.root.resolve()
    as_json = bool(args.json)

    if args.subcommand == "status":
        return cmd_status(root, as_json=as_json)
    if args.subcommand == "log":
        return cmd_log(root, limit=args.limit, as_json=as_json)
    if args.subcommand == "checkout":
        return cmd_checkout(root, args.snapshot_id)
    if args.subcommand == "doctor":
        return cmd_doctor(root, as_json=as_json)
    if args.subcommand == "gc":
        return cmd_gc(root, dry_run=args.dry_run, as_json=as_json)
    return 1


if __name__ == "__main__":
    sys.exit(main())
