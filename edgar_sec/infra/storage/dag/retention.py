"""Two-tier retention analysis and safe garbage collection for DAG snapshots.

Traces logical DAG reachability from roots using DAGCatalog, then cleans unreferenced snapshots.
"""

from __future__ import annotations

import shutil
from collections.abc import Set
from dataclasses import dataclass
from pathlib import Path

from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.paths import DAGPaths
from .publication import PublicationLock


@dataclass(frozen=True, slots=True)
class RetentionReport:
    """Analysis of retained vs safe-to-purge snapshot directories."""

    root_snapshots: tuple[str, ...]
    retained_snapshots: tuple[str, ...]
    prunable_snapshots: tuple[str, ...]
    prunable_byte_size: int


def discover_roots(
    snapshots_root: Path | str,
    extra_pinned_ids: Set[str] | None = None,
) -> set[str]:
    """Find branch/tag roots plus caller-supplied snapshot pins."""
    root = Path(snapshots_root)
    catalog = DAGCatalog(root)
    roots: set[str] = set()

    for branch_head in catalog.list_branches().values():
        roots.add(branch_head)

    for tag in catalog.list_tags():
        roots.add(tag["snapshot_id"])

    if extra_pinned_ids:
        roots.update(extra_pinned_ids)

    return roots


def analyze_retention(
    snapshots_root: Path | str,
    extra_pinned_ids: Set[str] | None = None,
    min_age_seconds: int = 0,
) -> RetentionReport:
    """Calculate reachable DAG nodes and identify unreferenced snapshots."""
    root = Path(snapshots_root)
    catalog = DAGCatalog(root)
    roots = discover_roots(root, extra_pinned_ids)
    retained: set[str] = set()

    for root_id in roots:
        manifests = catalog.walk_lineage(root_id)
        for m in manifests:
            retained.add(m.snapshot_id)
            if m.checkpoint_anchor_id:
                retained.add(m.checkpoint_anchor_id)
            base_pin = m.metadata.get("base_snapshot_id")
            if base_pin:
                retained.add(str(base_pin))

    all_snapshots = [s["snapshot_id"] for s in catalog.list_snapshots()]
    prunable: list[str] = []
    prunable_bytes = 0

    for s_id in all_snapshots:
        if s_id not in retained:
            prunable.append(s_id)
            target = root / s_id
            if target.is_dir():
                for f in target.rglob("*"):
                    if f.is_file():
                        prunable_bytes += f.stat().st_size

    # Also check legacy directories on disk if any
    if root.is_dir():
        for child in root.iterdir():
            if (
                child.is_dir()
                and not child.name.startswith(".")
                and child.name not in ("parts", "branches", "current")
                and child.name not in retained
                and child.name not in prunable
            ):
                prunable.append(child.name)
                for f in child.rglob("*"):
                    if f.is_file():
                        prunable_bytes += f.stat().st_size

    return RetentionReport(
        root_snapshots=tuple(sorted(roots)),
        retained_snapshots=tuple(sorted(retained)),
        prunable_snapshots=tuple(sorted(prunable)),
        prunable_byte_size=prunable_bytes,
    )


def purge_unreferenced(
    snapshots_root: Path | str,
    report: RetentionReport,
    *,
    dry_run: bool = False,
    extra_pinned_ids: Set[str] | None = None,
) -> list[str]:
    """Safely unlink snapshot directories and purge records from catalog under lock."""
    root = Path(snapshots_root)
    catalog = DAGCatalog(root)
    removed: list[str] = []
    lock_file = DAGPaths(root).publication_lock_path
    with PublicationLock(lock_file):
        rechecked = analyze_retention(root, extra_pinned_ids=extra_pinned_ids)
        safe_to_purge = set(report.prunable_snapshots) & set(
            rechecked.prunable_snapshots
        )
        for snap_id in sorted(safe_to_purge):
            target = root / snap_id
            if target.is_dir():
                if not dry_run:
                    shutil.rmtree(target)
            if not dry_run:
                with catalog._connect() as con:
                    con.execute("DELETE FROM nodes WHERE snapshot_id = ?", (snap_id,))
            removed.append(snap_id)
    return removed


__all__ = [
    "RetentionReport",
    "analyze_retention",
    "discover_roots",
    "purge_unreferenced",
]
