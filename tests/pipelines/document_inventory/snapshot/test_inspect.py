from __future__ import annotations

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.manifest import DAGNodeManifest, PartDescriptor
from edgar_sec.pipelines.document_inventory.paths import InventoryPaths
from edgar_sec.pipelines.document_inventory.snapshot.inspect import inspect_snapshot
from edgar_sec.pipelines.document_inventory.snapshot.schema import (
    SNAPSHOT_ACCESSIONS_SCHEMA,
)


def test_inspect_pins_current_snapshot_and_reports_verified_parts(tmp_path) -> None:
    paths = InventoryPaths(tmp_path)
    snapshot_id = "snapshot-a"
    part_path = paths.snapshots_root / snapshot_id / "accessions" / "part-00000.parquet"
    part_path.parent.mkdir(parents=True)
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "accession": "0000320193-24-000001",
                    "filing_cik": "0000320193",
                    "form": "10-K",
                    "filing_date": "2024-01-15",
                    "report_date": "2023-12-31",
                    "bundle_url": "https://example.test/bundle.zip",
                    "bundle_size": 10,
                    "index_url": "https://example.test/index.html",
                    "index_sha256": "a" * 64,
                    "first_indexed_by": "run-1",
                }
            ],
            schema=SNAPSHOT_ACCESSIONS_SCHEMA,
        ),
        part_path,
    )
    descriptor = PartDescriptor(
        "accessions/part-00000.parquet",
        file_sha256(part_path),
        1,
        part_path.stat().st_size,
        "0000320193-24-000001",
        "0000320193-24-000001",
    )
    catalog = DAGCatalog(paths.snapshots_root)
    catalog.record_node(
        DAGNodeManifest(
            snapshot_id=snapshot_id,
            kind="checkpoint",
            parents=(),
            checkpoint_anchor_id=snapshot_id,
            lineage_depth=0,
            created_at="2026-01-01T00:00:00Z",
            relations={"accessions": (descriptor,)},
            logical_fingerprint="fingerprint-a",
        )
    )
    catalog.write_pointer("main", snapshot_id)

    report = inspect_snapshot(paths)

    assert report["snapshot_id"] == snapshot_id
    assert report["lineage"] == [snapshot_id]
    assert report["partition_layout"]["physical_partition_key"] == "relation"
    assert report["partition_layout"]["annual_partitioning"] is False
    assert report["counts_by_form_filing_year"] == [
        {"form": "10-K", "filing_year": "2024", "accession_count": 1}
    ]
    assert report["parts"][0]["sha256"] == file_sha256(part_path)
    assert report["active_row_counts"]["accessions"] == 1


def test_inspect_rejects_a_dangling_branch_tip(tmp_path) -> None:
    paths = InventoryPaths(tmp_path)
    paths.snapshots_root.mkdir(parents=True)
    DAGCatalog(paths.snapshots_root).write_pointer("main", "missing")

    try:
        inspect_snapshot(paths)
    except ValueError as error:
        assert "not published" in str(error) or "manifest" in str(error)
    else:
        raise AssertionError("inspection accepted a dangling snapshot pointer")
