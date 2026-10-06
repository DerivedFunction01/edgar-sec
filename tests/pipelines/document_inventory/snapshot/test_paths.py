from __future__ import annotations

from pathlib import Path

import pytest

import edgar_sec.foundation.runtime.paths as foundation_paths
from edgar_sec.pipelines.document_inventory.paths import InventoryRunPaths
from edgar_sec.pipelines.document_inventory.snapshot.paths import SnapshotPaths


def test_snapshot_paths_resolve_shared_snapshot_layout(tmp_path: Path) -> None:
    paths = SnapshotPaths(tmp_path, "snapshot-1")

    expected_root = tmp_path / "document_inventory" / foundation_paths.SNAPSHOTS_DIR
    assert paths.snapshots_root == expected_root
    assert paths.manifest_path() == expected_root / "snapshot-1" / "manifest.json"
    assert paths.accessions_part_path("2025", 3) == (
        expected_root / "snapshot-1" / "accessions" / "year=2025" / "part-3.part"
    )
    assert paths.lookup_shard_path("forms", "a-f") == (
        expected_root / "snapshot-1" / "lookups" / "forms" / "shard=a-f" / "part-0.part"
    )


def test_snapshot_staging_requires_owning_run_paths(tmp_path: Path) -> None:
    paths = SnapshotPaths(tmp_path, "snapshot-1")

    with pytest.raises(RuntimeError, match="owning InventoryRunPaths"):
        _ = paths.staging_root


def test_snapshot_staging_is_scoped_to_owning_run(tmp_path: Path) -> None:
    run = InventoryRunPaths(tmp_path, "run-1")
    paths = SnapshotPaths(tmp_path, "snapshot-1", base=run)

    assert paths.staging_root == run.publication_dir() / ".staging-snapshot-1"
    assert paths.staging_manifest_path == paths.staging_root / "manifest.json"
