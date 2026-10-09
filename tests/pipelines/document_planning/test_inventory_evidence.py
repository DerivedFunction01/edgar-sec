from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.document_inventory.schemas import ENTRY_SCHEMA
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.manifest import DAGNodeManifest, PartDescriptor
from edgar_sec.pipelines.document_inventory.paths import InventoryPaths
from edgar_sec.pipelines.document_inventory.schemas import (
    INVENTORY_ACCESSIONS_SCHEMA,
    INVENTORY_RELATIONS,
)
from edgar_sec.pipelines.document_planning.inventory_evidence import (
    CatalogAccessionScopeRow,
    InventoryEvidenceError,
    open_inventory_evidence,
)

_ACCESSIONS = (
    "0000320193-24-000001",
    "0000320193-24-000002",
    "0000320193-24-000003",
)


def _write_snapshot(root: Path) -> tuple[InventoryPaths, Path]:
    paths = InventoryPaths(root)
    snapshot_id = "inventory-1"
    snapshot_root = paths.snapshot_root(snapshot_id)
    accessions_path = snapshot_root / "accessions" / "part-00000.parquet"
    entries_path = snapshot_root / "entries" / "part-00000.parquet"
    accessions_path.parent.mkdir(parents=True)
    entries_path.parent.mkdir(parents=True)
    accessions = [
        {
            "accession": accession,
            "filing_cik": accession[:10],
            "form": "10-K",
            "filing_date": "2024-01-15",
            "report_date": "2023-12-31",
            "bundle_url": f"https://www.sec.gov/Archives/edgar/data/320193/{accession.replace('-', '')}/{accession}.txt",
            "bundle_size": 120,
            "index_url": "https://www.sec.gov/index.html",
            "index_sha256": "a" * 64,
            "first_indexed_by": "run-1",
        }
        for accession in _ACCESSIONS[:2]
    ]
    pq.write_table(
        pa.Table.from_pylist(accessions, schema=INVENTORY_ACCESSIONS_SCHEMA),
        accessions_path,
    )
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "entry_id": "entry-1",
                    "accession": _ACCESSIONS[0],
                    "table_kind": "document_format",
                    "row_ordinal": 0,
                    "sequence": 1,
                    "document_type": "10-K",
                    "document_label": "Annual report",
                    "description": "Annual report",
                    "filename": "annual.htm",
                    "href": "annual.htm",
                    "archive_url": "https://www.sec.gov/annual.htm",
                    "byte_size": 500,
                }
            ],
            schema=ENTRY_SCHEMA,
        ),
        entries_path,
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
            relations={
                "accessions": (
                    PartDescriptor(
                        "accessions/part-00000.parquet",
                        file_sha256(accessions_path),
                        2,
                        accessions_path.stat().st_size,
                        _ACCESSIONS[0],
                        _ACCESSIONS[1],
                    ),
                ),
                "entries": (
                    PartDescriptor(
                        "entries/part-00000.parquet",
                        file_sha256(entries_path),
                        1,
                        entries_path.stat().st_size,
                        _ACCESSIONS[0],
                        _ACCESSIONS[0],
                    ),
                ),
            },
            logical_fingerprint="inventory-fingerprint",
            schema_versions={"accessions": "1", "entries": "1"},
        )
    )
    catalog.write_pointer("main", snapshot_id)
    return paths, accessions_path


def _scope_rows() -> tuple[CatalogAccessionScopeRow, ...]:
    return tuple(
        CatalogAccessionScopeRow(accession, "10-K", "2024-01-15")
        for accession in _ACCESSIONS
    )


def _open_source(paths: InventoryPaths):
    return open_inventory_evidence(paths, "inventory-1", INVENTORY_RELATIONS)


def test_named_snapshot_pin_streams_only_catalog_accessions(tmp_path: Path) -> None:
    paths, _ = _write_snapshot(tmp_path)
    source = _open_source(paths)
    DAGCatalog(paths.snapshots_root).write_pointer("main", "moved-after-pin")

    evidence = list(source.stream(_scope_rows(), batch_size=1))

    assert source.snapshot_id == "inventory-1"
    assert len(source.snapshot_digest) == 64
    assert [(row.accession, row.indexed) for row in evidence] == [
        (_ACCESSIONS[0], True),
        (_ACCESSIONS[1], True),
        (_ACCESSIONS[2], False),
    ]
    assert evidence[0].accession_row["bundle_size"] == 120
    assert evidence[0].entry_row["entry_id"] == "entry-1"
    assert evidence[1].entry_row is None
    assert evidence[2].accession_row is None
    assert evidence[2].entry_row is None


def test_named_snapshot_is_required(tmp_path: Path) -> None:
    paths, _ = _write_snapshot(tmp_path)
    with pytest.raises(InventoryEvidenceError, match="named snapshot ID"):
        open_inventory_evidence(paths, "current", INVENTORY_RELATIONS)


def test_snapshot_part_digest_is_verified_before_streaming(tmp_path: Path) -> None:
    paths, accessions_path = _write_snapshot(tmp_path)
    with accessions_path.open("ab") as stream:
        stream.write(b"corrupt")

    with pytest.raises(InventoryEvidenceError, match="part validation failed"):
        _open_source(paths)


def test_indexed_accession_form_and_date_must_match_catalog(tmp_path: Path) -> None:
    paths, _ = _write_snapshot(tmp_path)
    source = _open_source(paths)
    scope = (CatalogAccessionScopeRow(_ACCESSIONS[0], "20-F", "2024-01-15"),)

    with pytest.raises(InventoryEvidenceError, match="facts disagree"):
        list(source.stream(scope))


def test_scope_stream_must_be_unique_and_sorted(tmp_path: Path) -> None:
    paths, _ = _write_snapshot(tmp_path)
    source = _open_source(paths)
    scope = (
        CatalogAccessionScopeRow(_ACCESSIONS[1], "10-K", "2024-01-15"),
        CatalogAccessionScopeRow(_ACCESSIONS[0], "10-K", "2024-01-15"),
    )

    with pytest.raises(InventoryEvidenceError, match="unique and sorted"):
        list(source.stream(scope))
