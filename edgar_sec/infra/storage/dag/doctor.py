"""Graph integrity auditor and diagnostic repair tools for DAG snapshots.

Detects cycles, dangling parents, corrupted part digests, and orphaned staging dirs using DAGCatalog.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.paths import DAGPaths
from .retention import discover_roots
from .traversal import CycleDetectedError, walk_lineage


@dataclass(frozen=True, slots=True)
class GraphAudit:
    """Comprehensive diagnostic health report of a DAG snapshot repository."""

    is_healthy: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...]
    active_tips: tuple[str, ...]
    stale_staging_dirs: tuple[str, ...]


def _resolve_part_path(root: Path, snapshot_id: str, part_path: str | Path) -> Path:
    p = Path(part_path)
    if p.is_absolute():
        return p
    if (root / snapshot_id / p).is_file():
        return root / snapshot_id / p
    if (root / p).is_file():
        return root / p
    return root / snapshot_id / p


def audit_graph(
    snapshots_root: Path | str, *, verify_digests: bool = False
) -> GraphAudit:
    """Audit the physical and logical integrity of all snapshots under root."""
    root = Path(snapshots_root)
    paths = DAGPaths(root)
    catalog = DAGCatalog(root)
    errors: list[str] = []
    warnings: list[str] = []
    stale_stages: list[str] = []
    roots = discover_roots(root)

    for tip in sorted(roots):
        try:
            walk_lineage(root, tip)
        except CycleDetectedError as exc:
            errors.append(f"cycle in active lineage for {tip}: {exc}")
        except Exception as exc:
            errors.append(f"broken lineage for {tip}: {exc}")

    sql_audit = catalog.audit_graph()
    for cycle_root in sql_audit.get("cycles", []):
        errors.append(f"cycle detected in graph involving {cycle_root}")
    for orphan in sql_audit.get("orphan_nodes", []):
        errors.append(
            f"orphan node {orphan['snapshot_id']} references missing parent {orphan['parent_id']}"
        )

    now = time.time()
    if root.is_dir():
        for child in root.iterdir():
            if child.is_dir() and paths.is_staging_name(child.name):
                if now - child.stat().st_mtime > 86400:
                    stale_stages.append(child.name)

    snapshots = catalog.list_snapshots()
    for s_info in snapshots:
        manifest = catalog.get_manifest(s_info["snapshot_id"])
        if manifest is None:
            continue
        for _rel_name, parts in manifest.relations.items():
            for part in parts:
                part_path = _resolve_part_path(root, manifest.snapshot_id, part.path)
                if not part_path.is_file():
                    errors.append(
                        f"missing part file {part.path} in {manifest.snapshot_id}"
                    )
                    continue
                if part_path.stat().st_size != part.byte_size:
                    errors.append(
                        f"byte size mismatch for {part.path} in {manifest.snapshot_id}"
                    )
                    continue
                if verify_digests and file_sha256(part_path) != part.sha256:
                    errors.append(
                        f"digest mismatch for {part.path} in {manifest.snapshot_id}"
                    )

    return GraphAudit(
        is_healthy=len(errors) == 0,
        errors=tuple(errors),
        warnings=tuple(warnings),
        active_tips=tuple(sorted(roots)),
        stale_staging_dirs=tuple(sorted(stale_stages)),
    )


__all__ = ["GraphAudit", "audit_graph"]
