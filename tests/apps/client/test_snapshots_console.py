"""Tests for SnapshotConsole tagging, branch introspection, and retention gc."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.apps.client.snapshots import SnapshotConsole
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.manifest import DAGNodeManifest
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths


def test_snapshots_console_tag_and_branches(tmp_path: Path) -> None:
    """Verify tagging snapshots and reading branch pointers via SnapshotConsole."""
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    catalog = DAGCatalog(paths.snapshots_root)

    manifest = DAGNodeManifest(
        snapshot_id="snap-001",
        kind="checkpoint",
        parents=(),
        checkpoint_anchor_id="snap-001",
        lineage_depth=0,
        created_at="2026-01-01T00:00:00Z",
        relations={},
        logical_fingerprint="",
    )
    catalog.publish_node(manifest, branch_name="main")

    console = SnapshotConsole(artifacts_root=tmp_path)
    assert console.current() == "snap-001"
    assert "main" in console.branches()

    console.tag("v1.0", "snap-001", message="initial release")
    tags = console.tags()
    assert len(tags) == 1
    assert tags[0]["name"] == "v1.0"
    assert tags[0]["snapshot_id"] == "snap-001"

    assert console.get_tag("v1.0") is not None
    assert console.delete_tag("v1.0") is True
    assert len(console.tags()) == 0


def test_snapshots_console_gc(tmp_path: Path) -> None:
    """Verify SnapshotConsole gc collects unreferenced snapshots safely."""
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    catalog = DAGCatalog(paths.snapshots_root)

    manifest = DAGNodeManifest(
        snapshot_id="snap-keep",
        kind="checkpoint",
        parents=(),
        checkpoint_anchor_id="snap-keep",
        lineage_depth=0,
        created_at="2026-01-01T00:00:00Z",
        relations={},
        logical_fingerprint="",
    )
    catalog.publish_node(manifest, branch_name="main")

    console = SnapshotConsole(artifacts_root=tmp_path)
    gc_res = console.gc(dry_run=True)
    assert gc_res["dry_run"] is True
    assert "reclaimed_bytes" in gc_res
