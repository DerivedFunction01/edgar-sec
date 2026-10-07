from __future__ import annotations

from pathlib import Path

import pytest

import edgar_sec.foundation.runtime.paths as foundation_paths
from edgar_sec.pipelines.document_inventory.paths import InventoryPaths


def test_inventory_paths_resolve_snapshot_layout(tmp_path: Path) -> None:
    paths = InventoryPaths(tmp_path)

    expected_root = tmp_path / "document_inventory" / foundation_paths.SNAPSHOTS_DIR
    assert paths.snapshots_root == expected_root
    assert paths.snapshot_part_path("snapshot-1", "accessions", "2025", 3) == (
        expected_root / "snapshot-1" / "accessions" / "year=2025" / "part-00003.parquet"
    )
    assert paths.publication_lock_path == expected_root / "publication.lock"
