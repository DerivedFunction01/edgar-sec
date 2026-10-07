"""Immutable snapshot tag management.

Provides persistence, resolution, and lifecycle methods for snapshot tags.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.atomic import atomic_write_json
from .publication import PublicationLock


def tag_path_for(snapshots_root: Path | str, tag_name: str) -> Path:
    """Return filesystem path to a tag JSON file."""
    return Path(snapshots_root) / "tags" / f"{tag_name}.json"


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
    root = Path(snapshots_root)
    manifest_path = root / snapshot_id / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"snapshot manifest missing: {manifest_path}")

    lock_file = root / ".publication.lock"
    tag_path = tag_path_for(root, tag_name)
    digest = file_sha256(manifest_path)
    payload = {
        "tag": tag_name,
        "snapshot_id": snapshot_id,
        "manifest_sha256": digest,
        "created_at": datetime.now(UTC).isoformat(),
        "message": message,
    }
    with PublicationLock(lock_file):
        if tag_path.exists():
            raise FileExistsError(f"tag already exists: {tag_name}")
        tag_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(tag_path, payload, canonical=True)
    return tag_path


def read_tag(snapshots_root: Path | str, tag_name: str) -> dict[str, Any] | None:
    """Return tag payload or None if the tag does not exist."""
    path = tag_path_for(snapshots_root, tag_name)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def list_tags(snapshots_root: Path | str) -> list[dict[str, Any]]:
    """Return all persisted tags ordered by tag name."""
    tags_dir = Path(snapshots_root) / "tags"
    if not tags_dir.is_dir():
        return []
    results: list[dict[str, Any]] = []
    for tag_file in sorted(tags_dir.glob("*.json")):
        try:
            data = json.loads(tag_file.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "tag" in data:
                results.append(data)
        except (OSError, json.JSONDecodeError):
            continue
    return results


def delete_tag(snapshots_root: Path | str, tag_name: str) -> bool:
    """Delete a tag under publication lock, returning True if deleted."""
    root = Path(snapshots_root)
    tag_path = tag_path_for(root, tag_name)
    lock_file = root / ".publication.lock"
    with PublicationLock(lock_file):
        if not tag_path.is_file():
            return False
        tag_path.unlink()
        return True


__all__ = [
    "create_tag",
    "delete_tag",
    "list_tags",
    "read_tag",
    "tag_path_for",
]
