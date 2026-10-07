"""Tests for snapshot tags management.
Verifies creation, immutability, listing, and deletion.
"""

from pathlib import Path
import pytest

from edgar_sec.infra.storage.dag.manifest import DAGNodeManifest, write_manifest
from edgar_sec.infra.storage.dag.tags import (
    create_tag,
    delete_tag,
    list_tags,
    read_tag,
    tag_path_for,
)


def _make_dummy_snapshot(root: Path, snapshot_id: str) -> None:
    snap_dir = root / snapshot_id
    snap_dir.mkdir(parents=True, exist_ok=True)
    manifest = DAGNodeManifest(
        snapshot_id=snapshot_id,
        kind="checkpoint",
        parents=(),
        checkpoint_anchor_id=snapshot_id,
        lineage_depth=0,
        created_at="2026-01-01T00:00:00Z",
        relations={},
        logical_fingerprint="dummy",
    )
    write_manifest(snap_dir / "manifest.json", manifest)


def test_tag_lifecycle(tmp_path: Path) -> None:
    """Test full tag creation, retrieval, listing, and deletion flow."""
    _make_dummy_snapshot(tmp_path, "c0")
    tag_path = create_tag(tmp_path, "v1.0", "c0", message="First release")
    assert tag_path == tag_path_for(tmp_path, "v1.0")
    assert tag_path.is_file()

    with pytest.raises(FileExistsError):
        create_tag(tmp_path, "v1.0", "c0")

    tag_data = read_tag(tmp_path, "v1.0")
    assert tag_data is not None
    assert tag_data["tag"] == "v1.0"
    assert tag_data["snapshot_id"] == "c0"
    assert tag_data["message"] == "First release"

    tags = list_tags(tmp_path)
    assert len(tags) == 1
    assert tags[0]["tag"] == "v1.0"

    assert delete_tag(tmp_path, "v1.0") is True
    assert read_tag(tmp_path, "v1.0") is None
    assert delete_tag(tmp_path, "v1.0") is False


def test_tag_fails_on_missing_snapshot(tmp_path: Path) -> None:
    """Test tag creation rejection when target snapshot manifest is absent."""
    with pytest.raises(FileNotFoundError):
        create_tag(tmp_path, "invalid", "nonexistent")
