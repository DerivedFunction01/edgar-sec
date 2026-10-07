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
