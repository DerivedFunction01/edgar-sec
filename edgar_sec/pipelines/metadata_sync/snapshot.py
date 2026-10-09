"""Resolve published metadata parts from the DAG catalog."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.manifest import DAGNodeManifest, PartDescriptor

from .paths import MetadataPaths

__all__ = ["SnapshotCatalogError", "SnapshotParts", "resolve_snapshot_parts"]


class SnapshotCatalogError(ValueError):
    """A DAG record does not resolve to a complete published relation."""


@dataclass(frozen=True, slots=True)
class SnapshotParts:
    snapshot: DAGNodeManifest
    relation: str
    descriptors: tuple[PartDescriptor, ...]
    paths: tuple[Path, ...]

    @property
    def part_count(self) -> int:
        return len(self.paths)

    @property
    def row_count(self) -> int:
        return sum(part.row_count for part in self.descriptors)


def resolve_snapshot_parts(
    metadata: MetadataPaths,
    snapshot_id: str,
    relation: str = "submissions",
    *,
    verify_digests: bool = True,
) -> SnapshotParts:
    try:
        catalog = DAGCatalog(metadata.snapshots_root, read_only=True)
    except FileNotFoundError as exc:
        raise SnapshotCatalogError(f"snapshot catalog not found: {exc}") from exc
    snapshot = catalog.get_manifest(snapshot_id)
    if snapshot is None:
        raise SnapshotCatalogError(f"snapshot is not catalogued: {snapshot_id}")
    descriptors = snapshot.relations.get(relation, ())
    if not descriptors:
        raise SnapshotCatalogError(
            f"snapshot {snapshot_id!r} has no {relation!r} relation"
        )
    try:
        part_paths = catalog.resolve_relation(
            snapshot_id,
            relation,
            relative_to=metadata.snapshot_dir(snapshot_id),
            verify_digests=verify_digests,
        )
    except ValueError as exc:
        raise SnapshotCatalogError(str(exc)) from exc
    return SnapshotParts(
        snapshot=snapshot,
        relation=relation,
        descriptors=tuple(descriptors),
        paths=part_paths,
    )
