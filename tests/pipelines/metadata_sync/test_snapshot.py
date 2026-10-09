"""Published metadata parts resolve exclusively through SQLite."""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.manifest import DAGNodeManifest, PartDescriptor
from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths
from edgar_sec.pipelines.metadata_sync.snapshot import (
    SnapshotCatalogError,
    resolve_snapshot_parts,
)


def _record_snapshot(
    root: Path,
    snapshot_id: str,
    values: tuple[bytes, ...],
    *,
    digest: bool = True,
) -> tuple[Path, ...]:
    metadata = resolve_metadata_paths(root)
    snapshot_dir = metadata.snapshot_dir(snapshot_id)
    descriptors = []
    paths = []
    for index, content in enumerate(values):
        path = snapshot_dir / "parts" / f"part-{index:05d}.parquet"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        paths.append(path)
        descriptors.append(
            PartDescriptor(
                path=path.relative_to(snapshot_dir).as_posix(),
                sha256=file_sha256(path) if digest else "",
                row_count=index + 1,
                byte_size=path.stat().st_size,
            )
        )
    DAGCatalog(metadata.snapshots_root).record_node(
        DAGNodeManifest(
            snapshot_id=snapshot_id,
            kind="checkpoint",
            parents=(),
            checkpoint_anchor_id=snapshot_id,
            lineage_depth=0,
            created_at="2026-10-09T00:00:00Z",
            relations={"submissions": tuple(descriptors)},
            logical_fingerprint=f"fingerprint-{snapshot_id}",
        )
    )
    return tuple(paths)


def test_snapshot_parts_resolve_in_relation_order(tmp_path: Path) -> None:
    expected = _record_snapshot(tmp_path, "snap", (b"one", b"two"))

    resolved = resolve_snapshot_parts(resolve_metadata_paths(tmp_path), "snap")

    assert resolved.paths == expected
    assert resolved.part_count == 2
    assert resolved.row_count == 3
    assert resolved.snapshot.snapshot_id == "snap"


def test_snapshot_directory_without_a_catalog_record_is_not_a_snapshot(
    tmp_path: Path,
) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    orphan = metadata.snapshot_dir("orphan")
    orphan.mkdir(parents=True)
    DAGCatalog(metadata.snapshots_root)

    with pytest.raises(SnapshotCatalogError, match="not catalogued"):
        resolve_snapshot_parts(metadata, "orphan")


def test_snapshot_part_digest_is_checked(tmp_path: Path) -> None:
    metadata = resolve_metadata_paths(tmp_path)
    (path,) = _record_snapshot(tmp_path, "snap", (b"published",))
    path.write_bytes(b"changed")

    with pytest.raises(SnapshotCatalogError, match="digest mismatch"):
        resolve_snapshot_parts(metadata, "snap")


def test_snapshot_relation_requires_part_digests(tmp_path: Path) -> None:
    _record_snapshot(tmp_path, "snap", (b"published",), digest=False)

    with pytest.raises(SnapshotCatalogError, match="digest mismatch"):
        resolve_snapshot_parts(resolve_metadata_paths(tmp_path), "snap")
