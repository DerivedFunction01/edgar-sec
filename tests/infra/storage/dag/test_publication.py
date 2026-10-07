"""Tests for snapshot publication locking and CAS pointer updates."""

from pathlib import Path

import pytest

from edgar_sec.infra.storage.dag.manifest import (
    DAGNodeManifest,
    ParentRef,
)
from edgar_sec.infra.storage.dag.publication import (
    PublicationLock,
    PublicationLockError,
    StaleParentError,
    create_branch,
    delete_branch,
    list_branches,
    publish_node,
    read_pointer,
)


def test_publication_lock_contention(tmp_path: Path) -> None:
    lock_file = tmp_path / ".lock"
    with PublicationLock(lock_file):
        with pytest.raises(PublicationLockError):
            PublicationLock(lock_file, blocking=False)


def test_publish_node_and_stale_parent(tmp_path: Path) -> None:
    # 1. Publish initial node c0
    c0_staged = tmp_path / "stage_c0"
    c0_staged.mkdir(parents=True)
    c0_manifest = DAGNodeManifest(
        snapshot_id="c0",
        kind="checkpoint",
        parents=(),
        checkpoint_anchor_id="c0",
        lineage_depth=0,
        created_at="2026-10-07T00:00:00Z",
        relations={},
        logical_fingerprint="fp0",
    )

    publish_node(tmp_path, c0_manifest, c0_staged, expected_parent_id=None)
    ptr0 = read_pointer(tmp_path)
    assert ptr0 is not None
    assert ptr0["snapshot_id"] == "c0"

    # 2. Publish d1 expecting c0 (delta lists c0 as parent)
    d1_staged = tmp_path / "stage_d1"
    d1_staged.mkdir(parents=True)
    d1_manifest = DAGNodeManifest(
        snapshot_id="d1",
        kind="delta",
        parents=(ParentRef("c0", ""),),
        checkpoint_anchor_id="c0",
        lineage_depth=1,
        created_at="2026-10-07T00:01:00Z",
        relations={},
        logical_fingerprint="fp1",
    )

    publish_node(tmp_path, d1_manifest, d1_staged, expected_parent_id="c0")
    ptr1 = read_pointer(tmp_path)
    assert ptr1 is not None
    assert ptr1["snapshot_id"] == "d1"

    # 3. Publish d2 expecting obsolete c0 raises StaleParentError
    d2_staged = tmp_path / "stage_d2"
    d2_staged.mkdir(parents=True)
    d2_manifest = DAGNodeManifest(
        snapshot_id="d2",
        kind="delta",
        parents=(ParentRef("d1", ""),),
        checkpoint_anchor_id="c0",
        lineage_depth=2,
        created_at="2026-10-07T00:02:00Z",
        relations={},
        logical_fingerprint="fp2",
    )

    with pytest.raises(StaleParentError):
        publish_node(tmp_path, d2_manifest, d2_staged, expected_parent_id="c0")


def test_publish_delta_mismatched_parent_raises(tmp_path: Path) -> None:
    """Delta node whose manifest parents don't include expected_parent_id is rejected."""
    c0_staged = tmp_path / "stage_c0"
    c0_staged.mkdir(parents=True)
    c0_manifest = DAGNodeManifest(
        snapshot_id="c0",
        kind="checkpoint",
        parents=(),
        checkpoint_anchor_id="c0",
        lineage_depth=0,
        created_at="2026-10-07T00:00:00Z",
        relations={},
        logical_fingerprint="fp0",
    )
    publish_node(tmp_path, c0_manifest, c0_staged, expected_parent_id=None)

    # d1 claims a different parent than the current pointer
    d1_staged = tmp_path / "stage_d1"
    d1_staged.mkdir(parents=True)
    d1_manifest = DAGNodeManifest(
        snapshot_id="d1",
        kind="delta",
        parents=(ParentRef("wrong_parent", ""),),
        checkpoint_anchor_id="c0",
        lineage_depth=1,
        created_at="2026-10-07T00:01:00Z",
        relations={},
        logical_fingerprint="fp1",
    )

    with pytest.raises(ValueError, match="not among manifest parents"):
        publish_node(tmp_path, d1_manifest, d1_staged, expected_parent_id="c0")


def test_branch_management(tmp_path: Path) -> None:
    """Verify branch creation, listing, and deletion under lock."""
    c0_staged = tmp_path / "stage_c0"
    c0_staged.mkdir(parents=True)
    manifest = DAGNodeManifest(
        snapshot_id="c0",
        kind="checkpoint",
        parents=(),
        checkpoint_anchor_id="c0",
        lineage_depth=0,
        created_at="2026-10-07T00:00:00Z",
        relations={},
        logical_fingerprint="fp0",
    )
    publish_node(tmp_path, manifest, c0_staged, expected_parent_id=None)

    branch_file = create_branch(tmp_path, "feature-x", "c0")
    assert branch_file.is_file()
    assert "feature-x" in list_branches(tmp_path)

    with pytest.raises(ValueError):
        create_branch(tmp_path, "current", "c0")

    assert delete_branch(tmp_path, "feature-x") is True
    assert "feature-x" not in list_branches(tmp_path)
    assert delete_branch(tmp_path, "nonexistent") is False
