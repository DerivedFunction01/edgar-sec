"""Tests for the relational DAGCatalog SQLite storage engine."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.manifest import (
    DAGNodeManifest,
    ParentRef,
    PartDescriptor,
)


def _make_manifest(
    snapshot_id: str,
    kind: str = "delta",
    parent_id: str | None = None,
    anchor_id: str = "snap_genesis",
    depth: int = 1,
    parts: list[PartDescriptor] | None = None,
) -> DAGNodeManifest:
    parents = (
        (ParentRef(snapshot_id=parent_id, manifest_sha256="hash1"),)
        if parent_id
        else ()
    )
    part_list = parts or [
        PartDescriptor(
            path=f"parts/submissions/{snapshot_id}.parquet",
            sha256="part_sha",
            row_count=100,
            byte_size=1024,
            key_min="0000000001",
            key_max="0000000100",
        )
    ]
    return DAGNodeManifest(
        snapshot_id=snapshot_id,
        kind="checkpoint" if kind == "checkpoint" else "delta",
        parents=parents,
        checkpoint_anchor_id=anchor_id,
        lineage_depth=depth,
        created_at="2024-01-01T00:00:00Z",
        relations={"submissions": tuple(part_list)},
        logical_fingerprint="fingerprint_test",
        metadata={"env": "test"},
    )


def test_schema_init_and_empty_state(tmp_path: Path) -> None:
    catalog = DAGCatalog(tmp_path)
    assert catalog.catalog_file.is_file()
    assert catalog.list_snapshots() == []
    assert catalog.read_pointer("main") is None


def test_publish_and_get_manifest(tmp_path: Path) -> None:
    catalog = DAGCatalog(tmp_path)
    genesis = _make_manifest(
        "snap_01", kind="checkpoint", parent_id=None, anchor_id="snap_01", depth=0
    )
    catalog.publish_node(genesis, branch_name="main")

    assert catalog.has_snapshot("snap_01")
    ptr = catalog.read_pointer("main")
    assert ptr is not None
    assert ptr["snapshot_id"] == "snap_01"

    loaded = catalog.get_manifest("snap_01")
    assert loaded is not None
    assert loaded.snapshot_id == "snap_01"
    assert loaded.kind == "checkpoint"
    assert "submissions" in loaded.relations
    assert len(loaded.relations["submissions"]) == 1
    assert loaded.relations["submissions"][0].row_count == 100


def test_lineage_and_active_parts(tmp_path: Path) -> None:
    catalog = DAGCatalog(tmp_path)
    snap0 = _make_manifest("snap_00", kind="checkpoint", anchor_id="snap_00", depth=0)
    snap1 = _make_manifest(
        "snap_01", kind="delta", parent_id="snap_00", anchor_id="snap_00", depth=1
    )
    snap2 = _make_manifest(
        "snap_02", kind="delta", parent_id="snap_01", anchor_id="snap_00", depth=2
    )

    catalog.publish_node(snap0, branch_name="main")
    catalog.publish_node(snap1, branch_name="main")
    catalog.publish_node(snap2, branch_name="main")

    lineage = catalog.walk_lineage("snap_02")
    assert [m.snapshot_id for m in lineage] == ["snap_00", "snap_01", "snap_02"]

    active_parts = catalog.get_active_parts("snap_02")
    assert len(active_parts) == 3

    pruned = catalog.prune_parts_for_range(
        "snap_02", "submissions", "0000000050", "0000000060"
    )
    assert len(pruned) == 3

    none_pruned = catalog.prune_parts_for_range(
        "snap_02", "submissions", "0000000200", "0000000300"
    )
    assert len(none_pruned) == 0


def test_branches_and_tags(tmp_path: Path) -> None:
    catalog = DAGCatalog(tmp_path)
    snap0 = _make_manifest("snap_00", kind="checkpoint", anchor_id="snap_00", depth=0)
    catalog.publish_node(snap0, branch_name="main")

    catalog.write_pointer("feature", "snap_00")
    branches = catalog.list_branches()
    assert branches["main"] == "snap_00"
    assert branches["feature"] == "snap_00"

    catalog.create_tag("v1.0", "snap_00", message="First release")
    tag = catalog.get_tag("v1.0")
    assert tag is not None
    assert tag["snapshot_id"] == "snap_00"
    assert tag["message"] == "First release"

    tags = catalog.list_tags()
    assert len(tags) == 1
    assert tags[0]["name"] == "v1.0"

    assert catalog.delete_tag("v1.0") is True
    assert catalog.get_tag("v1.0") is None


def test_audit_graph(tmp_path: Path) -> None:
    catalog = DAGCatalog(tmp_path)
    snap0 = _make_manifest("snap_00", kind="checkpoint", anchor_id="snap_00", depth=0)
    snap1 = _make_manifest(
        "snap_01", kind="delta", parent_id="snap_00", anchor_id="snap_00", depth=1
    )
    catalog.publish_node(snap0)
    catalog.publish_node(snap1)

    audit = catalog.audit_graph()
    assert audit["node_count"] == 2
    assert audit["part_count"] == 2
    assert audit["orphan_nodes"] == []
    assert audit["cycles"] == []


def test_find_snapshot_ids_by_metadata_is_read_only(tmp_path: Path) -> None:
    root = tmp_path / "snapshots"
    assert (
        DAGCatalog.find_snapshot_ids_by_metadata(root, "run_intent_id", "run-1") == ()
    )
    assert not root.exists()

    catalog = DAGCatalog(root)
    manifest = _make_manifest("snap-1")
    manifest = replace(manifest, metadata={"run_intent_id": "run-1"})
    catalog.record_node(manifest)
    before = {path.name for path in root.iterdir()}

    assert DAGCatalog.find_snapshot_ids_by_metadata(root, "run_intent_id", "run-1") == (
        "snap-1",
    )
    assert {path.name for path in root.iterdir()} == before
