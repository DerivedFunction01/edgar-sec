"""Tests for topological DAG lineage traversal and cycle detection."""

from pathlib import Path

import pytest

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.dag.manifest import (
    DAGNodeManifest,
    ParentRef,
    write_manifest,
)
from edgar_sec.infra.storage.dag.traversal import (
    BrokenLineageError,
    CycleDetectedError,
    DigestMismatchError,
    walk_lineage,
)


def _write_node(
    root: Path,
    snapshot_id: str,
    kind: str,
    parents: tuple[tuple[str, str], ...] = (),
    anchor: str = "",
) -> tuple[DAGNodeManifest, str]:
    snap_dir = root / snapshot_id
    snap_dir.mkdir(parents=True, exist_ok=True)
    manifest = DAGNodeManifest(
        snapshot_id=snapshot_id,
        kind="checkpoint" if kind == "checkpoint" else "delta",
        parents=tuple(
            ParentRef(snapshot_id=pid, manifest_sha256=phash) for pid, phash in parents
        ),
        checkpoint_anchor_id=anchor or snapshot_id,
        lineage_depth=len(parents),
        created_at="2026-10-07T00:00:00Z",
        relations={},
        logical_fingerprint="fp",
    )
    manifest_path = snap_dir / "manifest.json"
    write_manifest(manifest_path, manifest)
    return manifest, file_sha256(manifest_path)


def test_linear_lineage_traversal(tmp_path: Path) -> None:
    _, c0_hash = _write_node(tmp_path, "c0", "checkpoint")
    _, d1_hash = _write_node(
        tmp_path, "d1", "delta", parents=(("c0", c0_hash),), anchor="c0"
    )
    _write_node(tmp_path, "d2", "delta", parents=(("d1", d1_hash),), anchor="c0")

    chain = walk_lineage(tmp_path, "d2")
    assert chain.tip_id == "d2"
    assert chain.checkpoint_anchor_id == "c0"
    assert [n.snapshot_id for n in chain.nodes] == ["c0", "d1", "d2"]


def test_diamond_merge_traversal(tmp_path: Path) -> None:
    _, c0_hash = _write_node(tmp_path, "c0", "checkpoint")
    _, da_hash = _write_node(
        tmp_path, "da", "delta", parents=(("c0", c0_hash),), anchor="c0"
    )
    _, db_hash = _write_node(
        tmp_path, "db", "delta", parents=(("c0", c0_hash),), anchor="c0"
    )
    _write_node(
        tmp_path,
        "m",
        "delta",
        parents=(("da", da_hash), ("db", db_hash)),
        anchor="c0",
    )

    chain = walk_lineage(tmp_path, "m")
    node_ids = [n.snapshot_id for n in chain.nodes]
    assert node_ids[0] == "c0"
    assert "da" in node_ids
    assert "db" in node_ids
    assert node_ids[-1] == "m"
    assert len(node_ids) == 4  # c0 is not duplicated!


def test_cycle_detection(tmp_path: Path) -> None:
    # d1 -> d2 -> d1
    d1_dir = tmp_path / "d1"
    d2_dir = tmp_path / "d2"
    d1_dir.mkdir(parents=True, exist_ok=True)
    d2_dir.mkdir(parents=True, exist_ok=True)

    m1 = DAGNodeManifest(
        snapshot_id="d1",
        kind="delta",
        parents=(ParentRef(snapshot_id="d2", manifest_sha256=""),),
        checkpoint_anchor_id="c0",
        lineage_depth=1,
        created_at="2026-10-07T00:00:00Z",
        relations={},
        logical_fingerprint="fp",
    )
    write_manifest(d1_dir / "manifest.json", m1)

    m2 = DAGNodeManifest(
        snapshot_id="d2",
        kind="delta",
        parents=(ParentRef(snapshot_id="d1", manifest_sha256=""),),
        checkpoint_anchor_id="c0",
        lineage_depth=2,
        created_at="2026-10-07T00:00:00Z",
        relations={},
        logical_fingerprint="fp",
    )
    write_manifest(d2_dir / "manifest.json", m2)

    with pytest.raises(CycleDetectedError):
        walk_lineage(tmp_path, "d1")


def test_digest_mismatch_detection(tmp_path: Path) -> None:
    _write_node(tmp_path, "c0", "checkpoint")
    _write_node(tmp_path, "d1", "delta", parents=(("c0", "wrong_hash"),), anchor="c0")
    with pytest.raises(DigestMismatchError):
        walk_lineage(tmp_path, "d1")
