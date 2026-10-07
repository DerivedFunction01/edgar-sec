"""Graph integrity auditor and diagnostic repair tools for DAG snapshots.

Detects cycles, dangling parents, corrupted part digests, and orphaned staging dirs.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from edgar_sec.foundation.hashing import file_sha256

from .manifest import DAGNodeManifest, read_manifest
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
    errors: list[str] = []
    warnings: list[str] = []
    stale_stages: list[str] = []
    roots = discover_roots(root)

    # 1. Check active tips and verify ancestry traversal
    for tip in sorted(roots):
        try:
            walk_lineage(root, tip)
        except CycleDetectedError as exc:
            errors.append(f"cycle in active lineage for {tip}: {exc}")
        except Exception as exc:
            errors.append(f"broken lineage for {tip}: {exc}")

    # 2. Check all snapshot directories on disk
    now = time.time()
    for child in root.iterdir():
        if not child.is_dir():
            continue
        if child.name.startswith(".stage-"):
            if now - child.stat().st_mtime > 86400:
                stale_stages.append(child.name)
            continue
        if child.name in ("current", "branches"):
            continue

        manifest_file = child / "manifest.json"
        if not manifest_file.is_file():
            warnings.append(
                f"uncommitted snapshot directory without manifest: {child.name}"
            )
            continue

        try:
            manifest = read_manifest(manifest_file)
        except Exception as exc:
            errors.append(f"corrupted manifest at {child.name}: {exc}")
            continue

        # Check declared parts
        for rel_name, parts in manifest.relations.items():
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
