"""Inspect and query published acquisition snapshot DAGs."""

from __future__ import annotations

import argparse
import json
import sys

from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.snapshot.query import (
    get_snapshot_status,
    list_snapshots,
    query_snapshot_relation,
)


def cmd_snapshot_status(args: argparse.Namespace) -> int:
    """Show the status of the published acquisition snapshot on a branch."""
    paths = resolve_acquisition_paths(artifacts_root=args.artifacts)
    branch = getattr(args, "branch", "main")
    try:
        status = get_snapshot_status(paths, branch_name=branch)
    except (OSError, ValueError) as error:
        payload = {"command": "snapshot status", "error": str(error), "status": "error"}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"snapshot status failed: {error}", file=sys.stderr)
        return 1

    payload = {"command": "snapshot status", **status}
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    elif not status["published"]:
        print(f"No acquisition snapshot is published on branch {branch!r}.")
    else:
        print(
            f"Snapshot on branch {branch!r}: {status['snapshot_id']} "
            f"(kind={status['kind']}, depth={status['lineage_depth']})"
        )
        counts = ", ".join(
            f"{name}={count}"
            for name, count in sorted(status.get("relation_counts", {}).items())
            if count
        )
        if counts:
            print(f"  relations: {counts}")
    return 0


def cmd_snapshot_query(args: argparse.Namespace) -> int:
    """Query rows from a published acquisition snapshot relation."""
    paths = resolve_acquisition_paths(artifacts_root=args.artifacts)
    branch = getattr(args, "branch", "main")
    limit = getattr(args, "limit", 20)
    try:
        table = query_snapshot_relation(
            paths,
            args.relation,
            snapshot_id=getattr(args, "snapshot_id", None),
            branch_name=branch,
            limit=limit,
        )
    except (OSError, ValueError) as error:
        payload = {"command": "snapshot query", "error": str(error), "status": "error"}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"snapshot query failed: {error}", file=sys.stderr)
        return 1

    rows = table.to_pylist()
    if args.json:
        payload = {
            "command": "snapshot query",
            "relation": args.relation,
            "row_count": len(rows),
            "rows": rows,
        }
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"Relation {args.relation}: {len(rows)} row(s)")
        for row in rows:
            print("  " + json.dumps(row, sort_keys=True, default=str))
    return 0


def cmd_snapshot_list(args: argparse.Namespace) -> int:
    """List all published acquisition snapshots in the catalog."""
    paths = resolve_acquisition_paths(artifacts_root=args.artifacts)
    try:
        snapshots = list_snapshots(paths)
    except (OSError, ValueError) as error:
        payload = {"command": "snapshot list", "error": str(error), "status": "error"}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"snapshot list failed: {error}", file=sys.stderr)
        return 1

    if args.json:
        payload = {
            "command": "snapshot list",
            "count": len(snapshots),
            "snapshots": snapshots,
        }
        print(json.dumps(payload, sort_keys=True))
    elif not snapshots:
        print("No acquisition snapshots found.")
    else:
        for snap in snapshots:
            print(
                f"{snap['snapshot_id']}: kind={snap['kind']}, "
                f"parent={snap['parent_snapshot_id'] or '(root)'}"
            )
    return 0


__all__ = [
    "cmd_snapshot_list",
    "cmd_snapshot_query",
    "cmd_snapshot_status",
]
