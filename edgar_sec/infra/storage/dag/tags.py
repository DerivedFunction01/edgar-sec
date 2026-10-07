"""Immutable snapshot tag management.

Provides persistence, resolution, and lifecycle methods for snapshot tags in DAGCatalog.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from edgar_sec.infra.storage.dag.catalog import DAGCatalog


def tag_path_for(snapshots_root: Path | str, tag_name: str) -> Path:
    """Return catalog database path associated with tags."""
    return DAGCatalog(snapshots_root).catalog_file


def create_tag(
    snapshots_root: Path | str,
    tag_name: str,
    snapshot_id: str,
    *,
    message: str = "",
) -> Path:
    """Persist an immutable tag pointing to a verified snapshot manifest."""
    if not tag_name or "/" in tag_name:
        raise ValueError(f"invalid tag name: {tag_name!r}")
    catalog = DAGCatalog(snapshots_root)
    if not catalog.has_snapshot(snapshot_id):
        raise FileNotFoundError(f"snapshot manifest missing: {snapshot_id}")
    if catalog.get_tag(tag_name) is not None:
        raise FileExistsError(f"tag already exists: {tag_name}")
    catalog.create_tag(tag_name, snapshot_id, message)
    return catalog.catalog_file


def read_tag(snapshots_root: Path | str, tag_name: str) -> dict[str, Any] | None:
    """Return tag payload or None if the tag does not exist."""
    catalog = DAGCatalog(snapshots_root)
    tag = catalog.get_tag(tag_name)
    if tag is None:
        return None
    return {
        "tag": tag["name"],
        "snapshot_id": tag["snapshot_id"],
        "created_at": tag["created_at"],
        "message": tag["message"],
    }


def list_tags(snapshots_root: Path | str) -> list[dict[str, Any]]:
    """Return all persisted tags ordered by creation time."""
    catalog = DAGCatalog(snapshots_root)
    return [
        {
            "tag": t["name"],
            "snapshot_id": t["snapshot_id"],
            "created_at": t["created_at"],
            "message": t["message"],
        }
        for t in catalog.list_tags()
    ]


def delete_tag(snapshots_root: Path | str, tag_name: str) -> bool:
    """Delete a tag by name, returning True if deleted."""
    catalog = DAGCatalog(snapshots_root)
    return catalog.delete_tag(tag_name)


__all__ = [
    "create_tag",
    "delete_tag",
    "list_tags",
    "read_tag",
    "tag_path_for",
]
