"""DAG operator maintenance commands: doctor, compact, and gc."""

from __future__ import annotations

from pathlib import Path
import shutil
from collections.abc import Sequence

from ..paths import DAGPaths
from ..spec import RelationSpec
from ..working.compaction import compact_lineage
from ..working.publication import read_pointer
from ..working.retention import analyze_retention, purge_unreferenced
from ..working.traversal import walk_lineage
from .doctor import audit_graph
from .output import _emit


def cmd_doctor(
    snapshots_root: Path,
    *,
    verify_digests: bool = True,
    as_json: bool = False,
) -> int:
    """Run diagnostics on lineage and repository integrity."""
    audit = audit_graph(snapshots_root, verify_digests=verify_digests)
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


def cmd_compact(
    snapshots_root: Path,
    *,
    branch_name: str | None = None,
    specs: Sequence[RelationSpec],
    new_snapshot_id: str | None = None,
    publish: bool = True,
    as_json: bool = False,
) -> int:
    """Compact active lineage into a standalone Checkpoint snapshot."""
    if not specs:
        if as_json:
            _emit({"error": "compaction requires relation specs"})
        else:
            print("Compaction requires relation specs")
        return 1
    ptr = read_pointer(snapshots_root, branch_name=branch_name)
    if ptr is None:
        if as_json:
            _emit({"error": "no active snapshot pointer"})
        else:
            print(f"No active snapshot pointer in {snapshots_root}")
        return 1
    tip_id = str(ptr["snapshot_id"])
    lineage = walk_lineage(snapshots_root, tip_id)
    tip = lineage.nodes[-1]

    target_id = new_snapshot_id or f"{tip_id}_compacted"
    staged = DAGPaths(snapshots_root).staging_dir(target_id)
    try:
        manifest = compact_lineage(
            snapshots_root,
            specs,
            tip_id=tip_id,
            new_snapshot_id=target_id,
            staged_dir=staged,
            publish=publish,
            branch_name=branch_name,
        )
    finally:
        if staged.exists():
            shutil.rmtree(staged, ignore_errors=True)

    info = {
        "snapshot_id": manifest.snapshot_id,
        "kind": manifest.kind,
        "tip_id": tip_id,
        "checkpoint_anchor_id": manifest.checkpoint_anchor_id,
        "lineage_depth": manifest.lineage_depth,
        "logical_fingerprint": manifest.logical_fingerprint,
        "relations": {k: len(v) for k, v in manifest.relations.items()},
        "published": publish,
    }
    if as_json:
        _emit(info)
    else:
        print(f"Compacted {tip_id} -> {manifest.snapshot_id} (published={publish})")
        print(f"Logical fingerprint: {manifest.logical_fingerprint}")
    return 0


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


__all__ = [
    "cmd_compact",
    "cmd_doctor",
    "cmd_gc",
]
