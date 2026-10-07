"""Tests for high-level document inventory snapshot reader adapter."""

from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.domain.document_inventory.schemas import ENTRY_SCHEMA
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.dag.manifest import (
    DAGNodeManifest,
    ParentRef,
    PartDescriptor,
    write_manifest,
)
from edgar_sec.foundation.runtime.paths import current_pointer_path
from edgar_sec.pipelines.document_inventory.snapshot.reader import (
    get_accessions_by_cik,
    get_active_accession,
    get_active_entries,
)
from edgar_sec.pipelines.document_inventory.snapshot.schema import (
    SNAPSHOT_ACCESSION_SOURCES_SCHEMA,
    SNAPSHOT_ACCESSIONS_SCHEMA,
)


def _setup_inventory_dag(tmp_path: Path) -> None:
    c0_dir = tmp_path / "c0"
    c0_dir.mkdir(parents=True)
    c0_acc = c0_dir / "accessions" / "part-00000.parquet"
    c0_acc.parent.mkdir(parents=True)
    c0_ent = c0_dir / "entries" / "part-00000.parquet"
    c0_ent.parent.mkdir(parents=True)

    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "accession": "0000320193-24-000001",
                    "filing_cik": "0000320193",
                    "form": "10-K",
                    "filing_date": "2024-01-15",
                    "report_date": "2023-12-31",
                    "bundle_url": "https://sec.gov/bundle.zip",
                    "bundle_size": 100,
                    "index_url": "https://sec.gov/index.html",
                    "index_sha256": "a" * 64,
                    "first_indexed_by": "run-1",
                }
            ],
            schema=SNAPSHOT_ACCESSIONS_SCHEMA,
        ),
        c0_acc,
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "entry_id": "e-old-1",
                    "accession": "0000320193-24-000001",
                    "table_kind": "document_format",
                    "row_ordinal": 0,
                    "sequence": 1,
                    "document_type": "10-K",
                    "document_label": "Annual Report",
                    "description": "Annual Report",
                    "filename": "doc.htm",
                    "href": "doc.htm",
                    "archive_url": "https://sec.gov/doc.htm",
                    "byte_size": 500,
                }
            ],
            schema=ENTRY_SCHEMA,
        ),
        c0_ent,
    )

    c0_manifest = DAGNodeManifest(
        snapshot_id="c0",
        kind="checkpoint",
        parents=(),
        checkpoint_anchor_id="c0",
        lineage_depth=0,
        created_at="2026-01-01T00:00:00Z",
        relations={
            "accessions": (
                PartDescriptor(
                    "accessions/part-00000.parquet",
                    file_sha256(c0_acc),
                    1,
                    c0_acc.stat().st_size,
                    "0000320193-24-000001",
                    "0000320193-24-000001",
                ),
            ),
            "entries": (
                PartDescriptor(
                    "entries/part-00000.parquet",
                    file_sha256(c0_ent),
                    1,
                    c0_ent.stat().st_size,
                    "0000320193-24-000001",
                    "0000320193-24-000001",
                ),
            ),
        },
        logical_fingerprint="fp0",
    )
    c0_man_path = c0_dir / "manifest.json"
    write_manifest(c0_man_path, c0_manifest)

    # d1 refreshes accession 0000320193-24-000001 with new entry e-new-1
    d1_dir = tmp_path / "d1"
    d1_dir.mkdir(parents=True)
    d1_acc = d1_dir / "accessions" / "part-00000.parquet"
    d1_acc.parent.mkdir(parents=True)
    d1_ent = d1_dir / "entries" / "part-00000.parquet"
    d1_ent.parent.mkdir(parents=True)

    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "accession": "0000320193-24-000001",
                    "filing_cik": "0000320193",
                    "form": "10-K",
                    "filing_date": "2024-01-15",
                    "report_date": "2023-12-31",
                    "bundle_url": "https://sec.gov/bundle.zip",
                    "bundle_size": 120,
                    "index_url": "https://sec.gov/index.html",
                    "index_sha256": "b" * 64,
                    "first_indexed_by": "run-1",
                }
            ],
            schema=SNAPSHOT_ACCESSIONS_SCHEMA,
        ),
        d1_acc,
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "entry_id": "e-new-1",
                    "accession": "0000320193-24-000001",
                    "table_kind": "document_format",
                    "row_ordinal": 0,
                    "sequence": 1,
                    "document_type": "10-K",
                    "document_label": "Annual Report Refreshed",
                    "description": "Annual Report Refreshed",
                    "filename": "doc.htm",
                    "href": "doc.htm",
                    "archive_url": "https://sec.gov/doc.htm",
                    "byte_size": 600,
                }
            ],
            schema=ENTRY_SCHEMA,
        ),
        d1_ent,
    )

    d1_manifest = DAGNodeManifest(
        snapshot_id="d1",
        kind="delta",
        parents=(ParentRef("c0", file_sha256(c0_man_path)),),
        checkpoint_anchor_id="c0",
        lineage_depth=1,
        created_at="2026-01-01T00:01:00Z",
        relations={
            "accessions": (
                PartDescriptor(
                    "accessions/part-00000.parquet",
                    file_sha256(d1_acc),
                    1,
                    d1_acc.stat().st_size,
                    "0000320193-24-000001",
                    "0000320193-24-000001",
                ),
            ),
            "entries": (
                PartDescriptor(
                    "entries/part-00000.parquet",
                    file_sha256(d1_ent),
                    1,
                    d1_ent.stat().st_size,
                    "0000320193-24-000001",
                    "0000320193-24-000001",
                ),
            ),
        },
        logical_fingerprint="fp1",
    )
    d1_man_path = d1_dir / "manifest.json"
    write_manifest(d1_man_path, d1_manifest)
    atomic_write_json(
        current_pointer_path(tmp_path),
        {"snapshot_id": "d1", "manifest_sha256": file_sha256(d1_man_path)},
        canonical=True,
    )


def test_reader_empty_pointer(tmp_path: Path) -> None:
    """Verify reader functions gracefully handle absent snapshot pointer."""
    assert get_active_accession(tmp_path, "0000320193-24-000001") is None
    assert get_active_entries(tmp_path, "0000320193-24-000001") == []
    assert get_accessions_by_cik(tmp_path, "0000320193") == []


def test_reader_lookups_and_scoped_mask_supersession(tmp_path: Path) -> None:
    """Verify point lookups and supersession filtering of entries."""
    _setup_inventory_dag(tmp_path)

    acc = get_active_accession(tmp_path, "0000320193-24-000001")
    assert acc is not None
    assert acc["bundle_size"] == 120

    entries = get_active_entries(tmp_path, "0000320193-24-000001")
    assert len(entries) == 1
    assert entries[0]["entry_id"] == "e-new-1"

    ciks = get_accessions_by_cik(tmp_path, "0000320193")
    assert len(ciks) == 1
    assert ciks[0]["accession"] == "0000320193-24-000001"
