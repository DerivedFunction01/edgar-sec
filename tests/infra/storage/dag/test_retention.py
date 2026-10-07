"""Tests for two-tier retention analysis and safe garbage collection."""

from pathlib import Path

from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.manifest import (
    DAGNodeManifest,
    ParentRef,
)
from edgar_sec.infra.storage.dag.retention import (
    analyze_retention,
    purge_unreferenced,
)
from edgar_sec.infra.storage.dag.tags import create_tag


def _make_node(
    root: Path,
    snap_id: str,
    kind: str,
    parents: tuple[str, ...] = (),
    anchor: str = "c0",
    metadata: dict | None = None,
) -> None:
    catalog = DAGCatalog(root)
    manifest = DAGNodeManifest(
        snapshot_id=snap_id,
        kind="checkpoint" if kind == "checkpoint" else "delta",
        parents=tuple(ParentRef(p, "") for p in parents),
        checkpoint_anchor_id=anchor,
        lineage_depth=len(parents),
        created_at="2026-10-07T00:00:00Z",
        relations={},
        logical_fingerprint="fp",
        metadata=metadata or {},
    )
    catalog.record_node(manifest)


def test_retention_protects_branch_and_pins(tmp_path: Path) -> None:
    catalog = DAGCatalog(tmp_path)
    _make_node(tmp_path, "c0", "checkpoint", anchor="c0")
    _make_node(tmp_path, "d1", "delta", parents=("c0",), anchor="c0")
    _make_node(tmp_path, "d2", "delta", parents=("d1",), anchor="c0")
    _make_node(tmp_path, "d_branch", "delta", parents=("d1",), anchor="c0")
    _make_node(tmp_path, "d_orphan", "delta", parents=(), anchor="c0")

    # Set main branch to d2
    catalog.write_pointer("main", "d2")

    # Set branch to d_branch
    catalog.write_pointer("exhibits", "d_branch")

    report = analyze_retention(tmp_path)
    assert "d_orphan" in report.prunable_snapshots
    assert "c0" in report.retained_snapshots
    assert "d1" in report.retained_snapshots
    assert "d2" in report.retained_snapshots
    assert "d_branch" in report.retained_snapshots

    # Purge unreferenced
    purged = purge_unreferenced(tmp_path, report)
    assert purged == ["d_orphan"]
    assert not catalog.has_snapshot("d_orphan")
    assert catalog.has_snapshot("d1")


def test_retention_protects_tagged_snapshots(tmp_path: Path) -> None:
    """Verify tags protect non-branch snapshots from garbage collection."""
    catalog = DAGCatalog(tmp_path)
    _make_node(tmp_path, "c0", "checkpoint", anchor="c0")
    _make_node(tmp_path, "c_tagged", "checkpoint", anchor="c_tagged")

    catalog.write_pointer("main", "c0")
    create_tag(tmp_path, "release-1", "c_tagged")

    report = analyze_retention(tmp_path)
    assert "c_tagged" in report.retained_snapshots
    assert "c_tagged" not in report.prunable_snapshots


def test_retention_pins_checkpoints_and_base_snapshot_metadata(tmp_path: Path) -> None:
    """Verify bridge links (checkpoint_anchor_id, base_snapshot_id) are retained."""
    catalog = DAGCatalog(tmp_path)
    _make_node(tmp_path, "c0", "checkpoint", anchor="c0")
    _make_node(tmp_path, "d1", "delta", parents=("c0",), anchor="c0")
    _make_node(
        tmp_path,
        "d2",
        "delta",
        parents=("d1",),
        anchor="c0",
        metadata={"base_snapshot_id": "c0"},
    )

    catalog.write_pointer("main", "d2")
    report = analyze_retention(tmp_path)
    assert "c0" in report.retained_snapshots

    _make_node(tmp_path, "d3", "delta", parents=("d1",), anchor="c0")
    catalog.write_pointer("other", "d3")

    report = analyze_retention(tmp_path)
    assert "c0" in report.retained_snapshots

    _make_node(tmp_path, "standalone_cp", "checkpoint", anchor="standalone_cp")
    _make_node(tmp_path, "d4", "delta", parents=("d3",), anchor="standalone_cp")
    catalog.write_pointer("main", "d4")

    report = analyze_retention(tmp_path)
    assert "standalone_cp" in report.retained_snapshots

    _make_node(tmp_path, "base_snap", "checkpoint", anchor="base_snap")
    _make_node(
        tmp_path,
        "d5",
        "delta",
        parents=("d4",),
        anchor="standalone_cp",
        metadata={"base_snapshot_id": "base_snap"},
    )
    catalog.write_pointer("main", "d5")

    report = analyze_retention(tmp_path)
    assert "base_snap" in report.retained_snapshots
