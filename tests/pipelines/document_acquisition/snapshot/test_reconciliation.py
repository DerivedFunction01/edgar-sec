from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pytest

from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.manifest import DAGNodeManifest, PartDescriptor
from edgar_sec.infra.storage.parquet import write_parquet_table
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.snapshot.reconciliation import (
    reconcile_inventory_metadata,
)


def test_reconcile_missing_root_returns_zero(tmp_path: Path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    result = reconcile_inventory_metadata(
        paths,
        "snap-1",
        inventory_snapshots_root=tmp_path / "missing_inventory_root",
    )
    assert result == {"reconciled_slots": 0, "reconciled_types": 0}


def test_reconcile_missing_snapshot_raises(tmp_path: Path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    inv_root = tmp_path / "snapshots" / "document_inventory"
    inv_root.mkdir(parents=True, exist_ok=True)
    DAGCatalog(inv_root)

    with pytest.raises(ValueError, match="inventory snapshot not found"):
        reconcile_inventory_metadata(
            paths, "snap-missing", inventory_snapshots_root=inv_root
        )


def test_reconcile_inventory_entries(tmp_path: Path) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    inv_root = tmp_path / "snapshots" / "document_inventory"
    inv_root.mkdir(parents=True, exist_ok=True)
    catalog = DAGCatalog(inv_root)

    snap_id = "snap-inv-1"
    snap_dir = inv_root / snap_id
    rel_dir = snap_dir / "entries"
    rel_dir.mkdir(parents=True, exist_ok=True)

    part_file = rel_dir / "part-00000.parquet"
    table = pa.Table.from_pydict(
        {
            "accession": ["0000320193-23-000106", "0000320193-23-000106"],
            "sequence": [1, 2],
            "type_raw": ["10-K", "EX-31.1"],
            "type_normalized": ["10-K", "EX-31.1"],
        }
    )
    write_parquet_table(table, part_file)

    manifest = DAGNodeManifest(
        snapshot_id=snap_id,
        parents=(),
        created_at="2026-10-14T00:00:00Z",
        kind="checkpoint",
        checkpoint_anchor_id=snap_id,
        lineage_depth=1,
        relations={
            "entries": (
                PartDescriptor(
                    path=f"entries/{part_file.name}",
                    row_count=2,
                    byte_size=part_file.stat().st_size,
                    sha256="0" * 64,
                ),
            )
        },
        logical_fingerprint="0" * 64,
        schema_versions={"1": "1"},
    )
    catalog.record_node(manifest)

    result = reconcile_inventory_metadata(
        paths, snap_id, inventory_snapshots_root=inv_root
    )
    assert result == {"reconciled_slots": 2, "reconciled_types": 2}
