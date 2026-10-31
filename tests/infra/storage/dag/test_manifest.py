"""Tests for DAGNodeManifest models and serialization."""

from edgar_sec.infra.storage.dag.manifest import (
    DAGNodeManifest,
    ParentRef,
    PartDescriptor,
)


def test_manifest_roundtrip_with_multiple_parents() -> None:
    manifest = DAGNodeManifest(
        snapshot_id="snap-merge",
        kind="delta",
        parents=(
            ParentRef(snapshot_id="snap-p1", manifest_sha256="hash-1"),
            ParentRef(snapshot_id="snap-p2", manifest_sha256="hash-2"),
        ),
        checkpoint_anchor_id="snap-c0",
        lineage_depth=3,
        created_at="2026-10-07T00:00:00Z",
        relations={
            "submissions": (
                PartDescriptor(
                    path="part-0.parquet",
                    sha256="sha-1",
                    row_count=100,
                    byte_size=1024,
                    key_min="0001",
                    key_max="0100",
                ),
            )
        },
        logical_fingerprint="fingerprint-abc",
    )

    loaded = DAGNodeManifest.from_dict(manifest.to_dict())

    assert loaded.snapshot_id == "snap-merge"
    assert len(loaded.parents) == 2
    assert loaded.parent_snapshot_id == "snap-p1"
    assert loaded.parents[1].snapshot_id == "snap-p2"
    assert loaded.relations["submissions"][0].row_count == 100
