"""Tests for snapshot publication locking and CAS pointer updates."""

from pathlib import Path

import pytest

from edgar_sec.infra.storage.dag.manifest import (
    DAGNodeManifest,
    write_manifest,
)
from edgar_sec.infra.storage.dag.publication import (
    PublicationLock,
    PublicationLockError,
    StaleParentError,
    publish_node,
    read_pointer_id,
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
    write_manifest(c0_staged / "manifest.json", c0_manifest)

    publish_node(tmp_path, c0_manifest, c0_staged, expected_parent_id=None)
    assert read_pointer_id(tmp_path / "current" / "pointer.json") == "c0"

    # 2. Publish d1 expecting c0
    d1_staged = tmp_path / "stage_d1"
    d1_staged.mkdir(parents=True)
    d1_manifest = DAGNodeManifest(
        snapshot_id="d1",
        kind="delta",
        parents=(),
        checkpoint_anchor_id="c0",
        lineage_depth=1,
        created_at="2026-10-07T00:01:00Z",
        relations={},
        logical_fingerprint="fp1",
    )
    write_manifest(d1_staged / "manifest.json", d1_manifest)

    publish_node(tmp_path, d1_manifest, d1_staged, expected_parent_id="c0")
    assert read_pointer_id(tmp_path / "current" / "pointer.json") == "d1"

    # 3. Publish d2 expecting obsolete c0 raises StaleParentError
    d2_staged = tmp_path / "stage_d2"
    d2_staged.mkdir(parents=True)
    d2_manifest = DAGNodeManifest(
        snapshot_id="d2",
        kind="delta",
        parents=(),
        checkpoint_anchor_id="c0",
        lineage_depth=2,
        created_at="2026-10-07T00:02:00Z",
        relations={},
        logical_fingerprint="fp2",
    )
    write_manifest(d2_staged / "manifest.json", d2_manifest)

    with pytest.raises(StaleParentError):
        publish_node(tmp_path, d2_manifest, d2_staged, expected_parent_id="c0")
