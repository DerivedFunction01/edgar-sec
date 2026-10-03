"""Snapshot manifests: the durable identity of a published document snapshot.

A manifest is the *only* thing that makes a snapshot meaningful. The Parquet
bytes on disk are interchangeable — a manifest names which parts constitute the
snapshot, which snapshots it descends from, and a content fingerprint. Without
one, a consolidation cannot tell a source snapshot from an intermediate.

Two invariants shape this module:

**A snapshot is immutable.** Writing a manifest under an existing id is refused.
A published identity is referenced from other records, so overwriting it would
retroactively change what those references mean.

**The pointer is written last.** ``current_pointer_path`` names the snapshot a
reader should use. A pointer written before the manifest would send a reader to
a snapshot that does not exist yet, which is strictly worse than a stale pointer
to one that does.

Environment access goes through ``foundation.runtime.env``; manifests and plans
are persisted artifacts and must never carry machine-specific overrides.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from edgar_sec.foundation.hashing import sha256_text
from edgar_sec.foundation.runtime.paths import current_pointer_path
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.atomic import atomic_write_text

log = logging.getLogger("storage.manifests")

MANIFEST_NAME = "manifest.json"
PART_KIND_INDEX = "index"
PART_KIND_PAYLOAD = "payload"


class ManifestError(RuntimeError):
    """A snapshot manifest could not be read, written, or published."""


@dataclass(frozen=True, slots=True)
class SnapshotPart:
    """One physical part of a snapshot.

    Parts are byte-budgeted, so a snapshot is a *set* of files rather than one.
    ``doc_ids`` is the ordered document range the part covers, which is what
    lets a reader stream a quarter a part at a time instead of loading it all.
    """

    path: str
    kind: str
    doc_ids: tuple[str, ...] = ()
    row_count: int = 0
    byte_size: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "doc_ids": list(self.doc_ids),
            "row_count": self.row_count,
            "byte_size": self.byte_size,
        }

    @classmethod
    def from_dict(cls, row: dict[str, Any]) -> SnapshotPart:
        return cls(
            path=str(row.get("path") or ""),
            kind=str(row.get("kind") or ""),
            doc_ids=tuple(str(item) for item in row.get("doc_ids", ())),
            row_count=int(row.get("row_count") or 0),
            byte_size=int(row.get("byte_size") or 0),
        )


def now_iso() -> str:
    """Return an ISO-8601 UTC timestamp at second resolution."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def snapshot_identity(
    *,
    operation: str,
    source_snapshot_ids: set[str] | list[str],
    artifact_hashes: set[str] | list[str],
    schema_version: str,
) -> str:
    """Derive a deterministic snapshot id from what produced it.

    Deterministic on purpose: consolidating the same sources with the same
    content twice yields the same id, so a repeated consolidation is recognizably
    a no-op rather than a second, near-identical snapshot.
    """
    payload = {
        "operation": operation,
        "source_snapshot_ids": sorted(source_snapshot_ids),
        "artifact_hashes": sorted(artifact_hashes),
        "schema_version": schema_version,
    }
    return f"{operation}-{sha256_text(canonical_json(payload))[:16]}"


def snapshot_dir(snapshots_root: Path, snapshot_id: str) -> Path:
    """Return the directory for one snapshot.

    ``snapshots_root`` is the dataset's published root — ``ProjectPaths
    .documents_root`` — and each snapshot is a directory beside the ``current``
    pointer. The phase and dataset keys are absent from the path because they are
    already fixed by which root was passed; repeating them would only add a
    second place to look.
    """
    return Path(snapshots_root) / snapshot_id


def snapshots_dir(snapshots_root: Path) -> Path:
    """Return the root holding every published snapshot."""
    return Path(snapshots_root)


def write_manifest(
    snapshots_root: Path,
    manifest: dict[str, Any],
    *,
    dataset: str,
    phase: str,
    set_current: bool = True,
) -> Path:
    """Publish a snapshot manifest, refusing to overwrite an existing snapshot.

    ``dataset`` and ``phase`` name the publisher, and are the caller's to supply:
    which phase produced a snapshot is a fact about the pipeline, not about the
    machinery that makes the snapshot durable. Several phases publish through
    this one function, so a constant here would mislabel all but one of them.
    """
    snapshot_id = str(manifest.get("snapshot_id") or "")
    if not snapshot_id:
        raise ManifestError("manifest requires a snapshot_id")
    target = snapshot_dir(snapshots_root, snapshot_id)
    if (target / MANIFEST_NAME).is_file():
        raise ManifestError(f"snapshot {snapshot_id} already published at {target}")

    atomic_write_text(target / MANIFEST_NAME, canonical_json(manifest))
    if set_current:
        publish_pointer(
            snapshots_root,
            snapshot_id,
            str(manifest.get("run_id") or ""),
            dataset=dataset,
            phase=phase,
        )
    return target / MANIFEST_NAME


def read_manifest(snapshots_root: Path, snapshot_id: str) -> dict[str, Any]:
    """Read one snapshot's manifest."""
    path = snapshot_dir(snapshots_root, snapshot_id) / MANIFEST_NAME
    if not path.is_file():
        raise ManifestError(f"snapshot manifest not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def list_snapshots(
    snapshots_root: Path, manifest_name: str = MANIFEST_NAME
) -> list[dict[str, Any]]:
    """List every readable snapshot manifest, sorted by id.

    A snapshot whose manifest is unreadable is skipped with a warning rather than
    failing the listing: consolidation must still be able to see the healthy
    snapshots when one directory is damaged.

    ``manifest_name`` is a parameter because the directory scan, the
    warn-and-skip handling, and the parse are one concern, but the manifest
    filename is a per-pipeline convention: Phase 1 metadata publishes
    ``metadata.manifest.json`` where this module's own dataset publishes
    ``manifest.json``. Defaulting the parameter keeps existing callers unchanged
    and lets a second pipeline reuse the logic instead of copying it.
    """
    root = snapshots_dir(snapshots_root)
    if not root.is_dir():
        return []
    found: list[dict[str, Any]] = []
    for entry in sorted(root.iterdir()):
        manifest_path = entry / manifest_name
        if not manifest_path.is_file():
            continue
        try:
            found.append(json.loads(manifest_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("skipping unreadable snapshot %s: %s", entry.name, exc)
    return found


def publish_pointer(
    artifacts_root: Path,
    snapshot_id: str,
    run_id: str = "",
    *,
    dataset: str,
    phase: str,
) -> Path:
    """Point ``current`` at a snapshot whose manifest is already on disk."""
    root = Path(artifacts_root)
    root.mkdir(parents=True, exist_ok=True)
    pointer = current_pointer_path(root)
    payload = {
        "dataset": dataset,
        "phase": phase,
        "snapshot_id": snapshot_id,
        "run_id": run_id,
        "pointed_at": now_iso(),
    }
    atomic_write_text(pointer, canonical_json(payload))
    return pointer


def read_pointer(snapshots_root: Path) -> dict[str, Any] | None:
    """Read the pointer naming the currently published snapshot."""
    pointer = current_pointer_path(Path(snapshots_root))
    if not pointer.is_file():
        return None
    try:
        return json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("unreadable pointer at %s: %s", pointer, exc)
        return None


def resolved_parts(manifest: dict[str, Any], kind: str) -> tuple[SnapshotPart, ...]:
    """Return one snapshot's parts of a given kind, in stored order."""
    return tuple(
        SnapshotPart.from_dict(row)
        for row in manifest.get("resolved_parts", ())
        if str(row.get("kind")) == kind
    )


def dependents_of(
    manifests: list[dict[str, Any]], source_ids: set[str]
) -> dict[str, set[str]]:
    """Map each source snapshot to the snapshots that reference its parts.

    This is the guard that makes a purge safe. Two snapshots that share a part
    are physically entangled: deleting the source deletes bytes the dependent
    still needs, so the dependent must be consolidated first.
    """
    paths_by_snapshot: dict[str, set[str]] = {}
    for manifest in manifests:
        snapshot_id = str(manifest.get("snapshot_id") or "")
        paths_by_snapshot[snapshot_id] = {
            str(part.get("path")) for part in manifest.get("resolved_parts", ())
        }

    dependents: dict[str, set[str]] = {}
    for source_id in source_ids:
        source_paths = paths_by_snapshot.get(source_id, set())
        for snapshot_id, paths in paths_by_snapshot.items():
            if snapshot_id == source_id or snapshot_id in source_ids:
                continue
            if paths & source_paths:
                dependents.setdefault(source_id, set()).add(snapshot_id)
    return dependents


def expand_dependency_closure(snapshots_root: Path, selected: set[str]) -> set[str]:
    """Grow a selection until it includes everything that shares a part with it.

    A purge may only remove a snapshot once nothing retained still references its
    parts. Expanding the closure is how the caller finds the set that is safe to
    drop together, rather than discovering a violation halfway through a delete.
    """
    manifests = list_snapshots(snapshots_root)
    closure = set(selected)
    changed = True
    while changed:
        changed = False
        for values in dependents_of(manifests, closure).values():
            before = len(closure)
            closure.update(values)
            changed |= len(closure) != before
    return closure


@dataclass(frozen=True, slots=True)
class SnapshotReader:
    """Read-side view of one snapshot's manifest."""

    snapshots_root: Path
    snapshot_id: str
    manifest: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.manifest:
            object.__setattr__(
                self, "manifest", read_manifest(self.snapshots_root, self.snapshot_id)
            )

    @property
    def schema_version(self) -> str:
        return str(self.manifest.get("schema_version") or "1")

    @property
    def source_snapshot_ids(self) -> tuple[str, ...]:
        return tuple(str(item) for item in self.manifest.get("source_snapshot_ids", ()))

    def parts(self, kind: str) -> tuple[SnapshotPart, ...]:
        """Return this snapshot's parts of one kind."""
        return resolved_parts(self.manifest, kind)

    def logical_fingerprint(self) -> str:
        """Return the content fingerprint recorded for this snapshot."""
        return str(
            self.manifest.get("logical_fingerprint") or self.manifest.get("snapshot_id")
        )

    def part_path(self, part: SnapshotPart) -> Path:
        """Resolve a part's recorded path against *this snapshot's* directory.

        A recorded ``part.path`` is relative to the snapshot directory, not to
        the snapshots root: ``write_index_part(snapshot_dir, ...)`` stores
        ``snapshot_dir / part.path`` and ``read_part`` resolves it the same way.
        Anchoring at the root instead would drop the snapshot id and resolve
        every part of every snapshot into the same wrong location.
        """
        return snapshot_dir(self.snapshots_root, self.snapshot_id) / part.path


__all__ = [
    "MANIFEST_NAME",
    "PART_KIND_INDEX",
    "PART_KIND_PAYLOAD",
    "ManifestError",
    "SnapshotPart",
    "SnapshotReader",
    "dependents_of",
    "expand_dependency_closure",
    "list_snapshots",
    "now_iso",
    "publish_pointer",
    "read_manifest",
    "read_pointer",
    "resolved_parts",
    "snapshot_dir",
    "snapshot_identity",
    "snapshots_dir",
    "write_manifest",
]
