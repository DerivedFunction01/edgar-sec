"""Two-tier retention analysis and safe garbage collection for DAG snapshots.

Traces logical DAG reachability from roots, then ref-counts physical files.
"""

from __future__ import annotations

import json
import shutil
import time
from collections.abc import Set
from dataclasses import dataclass
from pathlib import Path

from edgar_sec.foundation.runtime.paths import current_pointer_path

from .manifest import read_manifest
from .publication import PublicationLock, read_pointer_id


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
    """Find all active root snapshot IDs from current, branches, and plan pins."""
    root = Path(snapshots_root)
    roots: set[str] = set()

    current_pointer = current_pointer_path(root)
    curr_id = read_pointer_id(current_pointer)
    if curr_id:
        roots.add(curr_id)

    branches_dir = root / "branches"
    if branches_dir.is_dir():
        for b_pointer in branches_dir.glob("*/pointer.json"):
            b_id = read_pointer_id(b_pointer)
            if b_id:
                roots.add(b_id)

    tags_dir = root / "tags"
    if tags_dir.is_dir():
        for tag_file in tags_dir.glob("*.json"):
            try:
                t_data = json.loads(tag_file.read_text(encoding="utf-8"))
                if isinstance(t_data, dict) and "snapshot_id" in t_data:
                    roots.add(str(t_data["snapshot_id"]))
            except (OSError, json.JSONDecodeError):
                continue

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
    roots = discover_roots(root, extra_pinned_ids)
    retained: set[str] = set()

    # Phase 1: Trace reachability from roots backward to checkpoint anchors
    for root_id in roots:
        to_visit = [root_id]
        while to_visit:
            curr = to_visit.pop()
            if curr in retained:
                continue
            manifest_file = root / curr / "manifest.json"
            if not manifest_file.is_file():
                continue
            retained.add(curr)
            node = read_manifest(manifest_file)
            if node.kind != "checkpoint":
                for parent_ref in node.parents:
                    to_visit.append(parent_ref.snapshot_id)

    # Phase 2: Find all snapshot directories on disk not in retained
    now = time.time()
    prunable: list[str] = []
    prunable_bytes = 0
    for child in root.iterdir():
        if (
            not child.is_dir()
            or child.name.startswith(".")
            or child.name in ("current", "branches")
        ):
            continue
        if child.name not in retained and (child / "manifest.json").is_file():
            age = now - child.stat().st_mtime
            if age >= min_age_seconds:
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
    """Safely unlink snapshot directories identified as prunable under lock."""
    root = Path(snapshots_root)
    removed: list[str] = []
    lock_file = root / ".publication.lock"
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
                removed.append(snap_id)
    return removed


__all__ = [
    "RetentionReport",
    "analyze_retention",
    "discover_roots",
    "purge_unreferenced",
]
