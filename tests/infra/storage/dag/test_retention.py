"""Tests for two-tier retention analysis and safe garbage collection."""

from pathlib import Path

from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.dag.manifest import (
    DAGNodeManifest,
    ParentRef,
    write_manifest,
)
from edgar_sec.infra.storage.dag.retention import (
    analyze_retention,
    purge_unreferenced,
)


def _make_node(
    root: Path, snap_id: str, kind: str, parents: tuple[str, ...] = ()
) -> None:
    snap_dir = root / snap_id
    snap_dir.mkdir(parents=True, exist_ok=True)
    manifest = DAGNodeManifest(
        snapshot_id=snap_id,
        kind="checkpoint" if kind == "checkpoint" else "delta",
        parents=tuple(ParentRef(p, "") for p in parents),
        checkpoint_anchor_id="c0",
        lineage_depth=len(parents),
        created_at="2026-10-07T00:00:00Z",
        relations={},
        logical_fingerprint="fp",
    )
    write_manifest(snap_dir / "manifest.json", manifest)


def test_retention_protects_branch_and_pins(tmp_path: Path) -> None:
    _make_node(tmp_path, "c0", "checkpoint")
    _make_node(tmp_path, "d1", "delta", parents=("c0",))
    _make_node(tmp_path, "d2", "delta", parents=("d1",))
    _make_node(tmp_path, "d_branch", "delta", parents=("d1",))
    _make_node(tmp_path, "d_orphan", "delta", parents=())

    # Set current to d2
    (tmp_path / "current").mkdir()
    atomic_write_json(tmp_path / "current" / "pointer.json", {"snapshot_id": "d2"})

    # Set branch to d_branch
    (tmp_path / "branches" / "exhibits").mkdir(parents=True)
    atomic_write_json(
        tmp_path / "branches" / "exhibits" / "pointer.json",
        {"snapshot_id": "d_branch"},
    )

    report = analyze_retention(tmp_path)
    assert "d_orphan" in report.prunable_snapshots
    assert "c0" in report.retained_snapshots
    assert "d1" in report.retained_snapshots
    assert "d2" in report.retained_snapshots
    assert "d_branch" in report.retained_snapshots

    # Purge unreferenced
    purged = purge_unreferenced(tmp_path, report)
    assert purged == ["d_orphan"]
    assert not (tmp_path / "d_orphan").exists()
    assert (tmp_path / "d1").exists()


def test_retention_protects_tagged_snapshots(tmp_path: Path) -> None:
    """Verify tags protect non-branch snapshots from garbage collection."""
    _make_node(tmp_path, "c0", "checkpoint")
    _make_node(tmp_path, "c_tagged", "checkpoint")

    (tmp_path / "current").mkdir()
    atomic_write_json(tmp_path / "current" / "pointer.json", {"snapshot_id": "c0"})

    from edgar_sec.infra.storage.dag.tags import create_tag

    create_tag(tmp_path, "release-1", "c_tagged")
    report = analyze_retention(tmp_path)
    assert "c_tagged" in report.retained_snapshots
    assert "c_tagged" not in report.prunable_snapshots


def test_retention_pins_checkpoints_and_base_snapshot_metadata(tmp_path: Path) -> None:
    """Verify bridge links (checkpoint_anchor_id, base_snapshot_id) are retained."""
    # c0 is a checkpoint, d1 is a delta child of c0
    _make_node(tmp_path, "c0", "checkpoint")
    _make_node(tmp_path, "d1", "delta", parents=("c0",))

    # d2 is a delta that references c0 only via checkpoint_anchor_id
    # and has a base_snapshot_id in metadata pointing to c0
    d2_dir = tmp_path / "d2"
    d2_dir.mkdir(parents=True)
    d2_manifest = DAGNodeManifest(
        snapshot_id="d2",
        kind="delta",
        parents=(ParentRef("d1", ""),),
        checkpoint_anchor_id="c0",
        lineage_depth=2,
        created_at="2026-10-07T00:02:00Z",
        relations={},
        logical_fingerprint="fp2",
        metadata={"base_snapshot_id": "c0"},
    )
    write_manifest(d2_dir / "manifest.json", d2_manifest)

    # Set current to d2
    (tmp_path / "current").mkdir()
    atomic_write_json(tmp_path / "current" / "pointer.json", {"snapshot_id": "d2"})

    # c0 is reachable via d2's parents, so it's retained
    report = analyze_retention(tmp_path)
    assert "c0" in report.retained_snapshots

    # Now remove d1 and d2 from the current branch pointer,
    # leaving only c0 referenced by d2's checkpoint_anchor_id and base_snapshot_id
    # Simulate: delete branch "exhibits" pointing to d2, but c0 is only reachable
    # through d2's bridge links if d2 itself were pruned.
    # More directly: create a scenario where c0 is only reachable via bridge links
    # from a node that IS retained.
    # Let's test: if we have a retained node whose checkpoint_anchor_id points to
    # an otherwise unreachable node, that anchor is retained too.

    # Create an independent branch with a node that has checkpoint_anchor_id=c0
    # but c0 is not in its parent chain
    _make_node(tmp_path, "d3", "delta", parents=("d1",))
    (tmp_path / "branches" / "other").mkdir(parents=True)
    atomic_write_json(
        tmp_path / "branches" / "other" / "pointer.json",
        {"snapshot_id": "d3"},
    )

    # c0 is retained via d3's parent chain (d3->d1->c0)
    report = analyze_retention(tmp_path)
    assert "c0" in report.retained_snapshots

    # Now test: a node whose checkpoint_anchor_id points to a snapshot
    # that is NOT in its parent chain and NOT in any other retained chain
    # should still retain the anchor target
    orphan_anchor_dir = tmp_path / "orphan_anchor"
    orphan_anchor_dir.mkdir(parents=True)
    orphan_anchor_manifest = DAGNodeManifest(
        snapshot_id="orphan_anchor",
        kind="delta",
        parents=(ParentRef("d3", ""),),
        checkpoint_anchor_id="c0",
        lineage_depth=3,
        created_at="2026-10-07T00:03:00Z",
        relations={},
        logical_fingerprint="fp_oa",
    )
    write_manifest(orphan_anchor_dir / "manifest.json", orphan_anchor_manifest)

    # Set current to orphan_anchor (which has d3 as parent, d3 has d1 as parent,
    # d1 has c0 as parent — so c0 is already retained via parent chain)
    # To test bridge-only retention, we need a node whose checkpoint_anchor_id
    # points to something NOT reachable via parents.

    # Create a standalone checkpoint that is NOT in any parent chain
    _make_node(tmp_path, "standalone_cp", "checkpoint")
    # d4 is a delta that lists standalone_cp as its checkpoint_anchor_id
    # but standalone_cp is NOT in d4's parent chain
    d4_dir = tmp_path / "d4"
    d4_dir.mkdir(parents=True)
    d4_manifest = DAGNodeManifest(
        snapshot_id="d4",
        kind="delta",
        parents=(ParentRef("d3", ""),),
        checkpoint_anchor_id="standalone_cp",
        lineage_depth=4,
        created_at="2026-10-07T00:04:00Z",
        relations={},
        logical_fingerprint="fp_d4",
    )
    write_manifest(d4_dir / "manifest.json", d4_manifest)

    # Point current to d4
    atomic_write_json(
        tmp_path / "current" / "pointer.json",
        {"snapshot_id": "d4"},
    )

    report = analyze_retention(tmp_path)
    # standalone_cp is retained via checkpoint_anchor_id bridge link
    assert "standalone_cp" in report.retained_snapshots

    # Now test base_snapshot_id metadata bridge
    _make_node(tmp_path, "base_snap", "checkpoint")
    d5_dir = tmp_path / "d5"
    d5_dir.mkdir(parents=True)
    d5_manifest = DAGNodeManifest(
        snapshot_id="d5",
        kind="delta",
        parents=(ParentRef("d4", ""),),
        checkpoint_anchor_id="standalone_cp",
        lineage_depth=5,
        created_at="2026-10-07T00:05:00Z",
        relations={},
        logical_fingerprint="fp_d5",
        metadata={"base_snapshot_id": "base_snap"},
    )
    write_manifest(d5_dir / "manifest.json", d5_manifest)

    atomic_write_json(
        tmp_path / "current" / "pointer.json",
        {"snapshot_id": "d5"},
    )

    report = analyze_retention(tmp_path)
    assert "base_snap" in report.retained_snapshots
