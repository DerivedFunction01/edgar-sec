"""Tests for snapshot compaction and the Logical Parity Gate."""

from pathlib import Path

import pyarrow as pa

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.compaction import compact_lineage
from edgar_sec.infra.storage.dag.manifest import (
    DAGNodeManifest,
    ParentRef,
    PartDescriptor,
)
from edgar_sec.infra.storage.dag.publication import read_pointer
from edgar_sec.infra.storage.dag.spec import RelationSpec
from edgar_sec.infra.storage.parquet import read_parquet_table, write_parquet_table
from edgar_sec.pipelines.document_inventory.snapshot.reader import (
    get_accession_bundle,
    get_accessions_by_cik,
    get_accessions_by_source_cik,
    get_active_accession,
    get_active_entries,
    query_accessions,
)
from edgar_sec.pipelines.document_inventory.snapshot.schema import (
    SNAPSHOT_ACCESSIONS_SCHEMA,
    SNAPSHOT_ACCESSION_SOURCES_SCHEMA,
)
from edgar_sec.pipelines.document_inventory.snapshot.specs import INVENTORY_RELATIONS
from edgar_sec.domain.document_inventory.schemas import ENTRY_SCHEMA

SCHEMA = pa.schema([("id", pa.string()), ("val", pa.int64())])


def test_compact_lineage_preserves_parity(tmp_path: Path) -> None:
    catalog = DAGCatalog(tmp_path)
    specs = (
        RelationSpec(
            name="records",
            schema=SCHEMA,
            primary_key=("id",),
            merge_strategy="upsert",
            sort_order=("id",),
        ),
    )

    # 1. Base C0: {"1": 10, "2": 20}
    c0_dir = tmp_path / "c0"
    c0_dir.mkdir(parents=True)
    c0_part = c0_dir / "records.parquet"
    write_parquet_table(
        pa.Table.from_arrays([pa.array(["1", "2"]), pa.array([10, 20])], schema=SCHEMA),
        c0_part,
    )
    c0_manifest = DAGNodeManifest(
        snapshot_id="c0",
        kind="checkpoint",
        parents=(),
        checkpoint_anchor_id="c0",
        lineage_depth=0,
        created_at="2026-10-07T00:00:00Z",
        relations={
            "records": (
                PartDescriptor(
                    "records.parquet",
                    file_sha256(c0_part),
                    2,
                    c0_part.stat().st_size,
                ),
            )
        },
        logical_fingerprint="fp0",
    )
    catalog.record_node(c0_manifest)

    # 2. Delta D1: update "2" to 99, add "3" to 30
    d1_dir = tmp_path / "d1"
    d1_dir.mkdir(parents=True)
    d1_part = d1_dir / "records.parquet"
    write_parquet_table(
        pa.Table.from_arrays([pa.array(["2", "3"]), pa.array([99, 30])], schema=SCHEMA),
        d1_part,
    )
    d1_manifest = DAGNodeManifest(
        snapshot_id="d1",
        kind="delta",
        parents=(ParentRef("c0", catalog.get_manifest_sha256("c0") or ""),),
        checkpoint_anchor_id="c0",
        lineage_depth=1,
        created_at="2026-10-07T00:01:00Z",
        relations={
            "records": (
                PartDescriptor(
                    "records.parquet",
                    file_sha256(d1_part),
                    2,
                    d1_part.stat().st_size,
                ),
            )
        },
        logical_fingerprint="fp1",
    )
    catalog.record_node(d1_manifest)

    # 3. Compact D1 into C1
    c1_staged = tmp_path / "stage_c1"
    compacted = compact_lineage(
        tmp_path, specs, tip_id="d1", new_snapshot_id="c1", staged_dir=c1_staged
    )

    assert compacted.snapshot_id == "c1"
    assert compacted.kind == "checkpoint"
    assert compacted.lineage_depth == 0
    assert compacted.checkpoint_anchor_id == "c1"
    assert "records" in compacted.relations
    assert compacted.relations["records"][0].row_count == 3


def test_inventory_queries_match_across_compaction(tmp_path: Path) -> None:
    catalog = DAGCatalog(tmp_path)
    snapshot_dir = tmp_path / "base"
    snapshot_dir.mkdir()
    tables = {
        "accessions": pa.Table.from_pylist(
            [
                {
                    "accession": "0000000001-24-000001",
                    "filing_cik": "0000000001",
                    "form": "10-K",
                    "filing_date": "2024-03-01",
                    "report_date": "2023-12-31",
                    "bundle_url": "bundle-1",
                    "bundle_size": 1000,
                    "index_url": "index-1",
                    "index_sha256": "index-hash-1",
                    "first_indexed_by": "run-1",
                },
                {
                    "accession": "0000000001-24-000002",
                    "filing_cik": "0000000001",
                    "form": "10-Q",
                    "filing_date": "2024-06-01",
                    "report_date": "2024-03-31",
                    "bundle_url": "bundle-2",
                    "bundle_size": 2000,
                    "index_url": "index-2",
                    "index_sha256": "index-hash-2",
                    "first_indexed_by": "run-1",
                },
            ],
            schema=SNAPSHOT_ACCESSIONS_SCHEMA,
        ),
        "entries": pa.Table.from_pylist(
            [
                {
                    "entry_id": "entry-1",
                    "accession": "0000000001-24-000001",
                    "table_kind": "document",
                    "row_ordinal": 0,
                    "sequence": 1,
                    "document_type": "10-K",
                    "document_label": "Annual report",
                    "description": "Annual report",
                    "filename": "annual.htm",
                    "href": "annual.htm",
                    "archive_url": "archive-1",
                    "byte_size": 500,
                },
                {
                    "entry_id": "entry-2",
                    "accession": "0000000001-24-000002",
                    "table_kind": "document",
                    "row_ordinal": 0,
                    "sequence": 1,
                    "document_type": "10-Q",
                    "document_label": "Quarterly report",
                    "description": "Quarterly report",
                    "filename": "quarterly.htm",
                    "href": "quarterly.htm",
                    "archive_url": "archive-2",
                    "byte_size": 600,
                },
            ],
            schema=ENTRY_SCHEMA,
        ),
        "accession_sources": pa.Table.from_pylist(
            [
                {
                    "accession": "0000000001-24-000001",
                    "source_cik": "0000000002",
                    "first_seen_by": "run-1",
                },
                {
                    "accession": "0000000001-24-000002",
                    "source_cik": "0000000001",
                    "first_seen_by": "run-1",
                },
            ],
            schema=SNAPSHOT_ACCESSION_SOURCES_SCHEMA,
        ),
    }
    relations = {}
    for relation, table in tables.items():
        part_path = snapshot_dir / f"{relation}.parquet"
        write_parquet_table(table, part_path)
        relations[relation] = (
            PartDescriptor(
                f"{relation}.parquet",
                file_sha256(part_path),
                table.num_rows,
                part_path.stat().st_size,
            ),
        )
    catalog.record_node(
        DAGNodeManifest(
            snapshot_id="base",
            kind="checkpoint",
            parents=(),
            checkpoint_anchor_id="base",
            lineage_depth=0,
            created_at="2026-10-07T00:00:00Z",
            relations=relations,
            logical_fingerprint="base-fingerprint",
        )
    )
    catalog.write_pointer("main", "base")

    def inventory_results(snapshot_id: str | None = None) -> dict[str, object]:
        query = {"snapshot_id": snapshot_id} if snapshot_id is not None else {}
        return {
            "accession": get_active_accession(
                tmp_path, "0000000001-24-000001", **query
            ),
            "entries": sorted(
                get_active_entries(tmp_path, "0000000001-24-000001", **query),
                key=lambda row: row["entry_id"],
            ),
            "filing_cik": sorted(
                get_accessions_by_cik(tmp_path, "0000000001", **query),
                key=lambda row: row["accession"],
            ),
            "source_cik": sorted(
                get_accessions_by_source_cik(tmp_path, "0000000002", **query),
                key=lambda row: row["accession"],
            ),
            "filtered": query_accessions(
                tmp_path,
                form="10-K",
                filing_cik="0000000001",
                source_cik="0000000002",
                **query,
            ),
            "bundle": get_accession_bundle(tmp_path, "0000000001-24-000001", **query),
        }

    before = inventory_results("base")
    compact_lineage(
        tmp_path,
        INVENTORY_RELATIONS,
        tip_id="base",
        new_snapshot_id="compacted",
        staged_dir=tmp_path / "stage_compacted",
        publish=True,
    )

    assert inventory_results("compacted") == before
    assert inventory_results() == before


def test_compact_lineage_multipart_budgeting(tmp_path: Path) -> None:
    specs = (
        RelationSpec(
            name="records",
            schema=SCHEMA,
            primary_key=("id",),
            merge_strategy="upsert",
            sort_order=("id",),
            max_rows_per_part=2,
            entity_key="id",
        ),
    )

    c0_dir = tmp_path / "c0"
    c0_dir.mkdir(parents=True)
    c0_part = c0_dir / "records.parquet"
    write_parquet_table(
        pa.Table.from_arrays(
            [pa.array(["1", "2", "3", "4"]), pa.array([10, 20, 30, 40])],
            schema=SCHEMA,
        ),
        c0_part,
    )
    c0_manifest = DAGNodeManifest(
        snapshot_id="c0",
        kind="checkpoint",
        parents=(),
        checkpoint_anchor_id="c0",
        lineage_depth=0,
        created_at="2026-10-07T00:00:00Z",
        relations={
            "records": (
                PartDescriptor(
                    "records.parquet",
                    file_sha256(c0_part),
                    4,
                    c0_part.stat().st_size,
                ),
            )
        },
        logical_fingerprint="fp0",
    )
    catalog = DAGCatalog(tmp_path)
    catalog.record_node(c0_manifest)

    c1_staged = tmp_path / "stage_c1"
    compacted = compact_lineage(
        tmp_path, specs, tip_id="c0", new_snapshot_id="c1", staged_dir=c1_staged
    )

    parts = compacted.relations["records"]
    assert len(parts) == 2
    assert parts[0].path == "records/part-00000.parquet"
    assert parts[0].row_count == 2
    assert parts[0].key_min == "1"
    assert parts[0].key_max == "2"

    assert parts[1].path == "records/part-00001.parquet"
    assert parts[1].row_count == 2
    assert parts[1].key_min == "3"
    assert parts[1].key_max == "4"


def test_compact_lineage_publish_advances_pointer(tmp_path: Path) -> None:
    """Verify compaction with publish=True atomically advances the pointer."""
    specs = (
        RelationSpec(
            name="records",
            schema=SCHEMA,
            primary_key=("id",),
            merge_strategy="upsert",
            sort_order=("id",),
        ),
    )
    c0_dir = tmp_path / "c0"
    c0_dir.mkdir(parents=True)
    c0_part = c0_dir / "records.parquet"
    write_parquet_table(
        pa.Table.from_arrays([pa.array(["1"]), pa.array([10])], schema=SCHEMA),
        c0_part,
    )
    c0_manifest = DAGNodeManifest(
        snapshot_id="c0",
        kind="checkpoint",
        parents=(),
        checkpoint_anchor_id="c0",
        lineage_depth=0,
        created_at="2026-10-07T00:00:00Z",
        relations={
            "records": (
                PartDescriptor(
                    "records.parquet",
                    file_sha256(c0_part),
                    1,
                    c0_part.stat().st_size,
                ),
            )
        },
        logical_fingerprint="fp0",
    )
    catalog = DAGCatalog(tmp_path)
    catalog.record_node(c0_manifest)
    catalog.write_pointer("main", "c0")

    c1_staged = tmp_path / "stage_c1"
    compacted = compact_lineage(
        tmp_path,
        specs,
        tip_id="c0",
        new_snapshot_id="c1",
        staged_dir=c1_staged,
        publish=True,
    )
    assert compacted.snapshot_id == "c1"
    ptr = read_pointer(tmp_path)
    assert ptr is not None
    assert ptr["snapshot_id"] == "c1"
    assert catalog.has_snapshot("c1")


def test_compact_lineage_scoped_mask_purging(tmp_path: Path) -> None:
    """Verify compaction purges masked entries under scoped_mask supersession."""
    catalog = DAGCatalog(tmp_path)
    parent_schema = pa.schema([("group_id", pa.string()), ("label", pa.string())])
    child_schema = pa.schema(
        [
            ("item_id", pa.string()),
            ("group_id", pa.string()),
            ("payload", pa.string()),
        ]
    )
    source_schema = pa.schema(
        [
            ("group_id", pa.string()),
            ("source_id", pa.string()),
        ]
    )

    specs = (
        RelationSpec(
            name="groups",
            schema=parent_schema,
            primary_key=("group_id",),
            merge_strategy="upsert",
            sort_order=("group_id",),
        ),
        RelationSpec(
            name="items",
            schema=child_schema,
            primary_key=("item_id",),
            merge_strategy="scoped_mask",
            parent_relation="groups",
            parent_join_key=("group_id",),
            sort_order=("group_id", "item_id"),
        ),
        RelationSpec(
            name="sources",
            schema=source_schema,
            primary_key=("group_id", "source_id"),
            merge_strategy="upsert",
            sort_order=("group_id", "source_id"),
        ),
    )

    # 1. Base C0: G1 (2 items), G2 (2 old items), G3 (1 item)
    c0_dir = tmp_path / "c0"
    c0_dir.mkdir(parents=True)
    p_c0_grp = c0_dir / "groups.parquet"
    p_c0_itm = c0_dir / "items.parquet"
    p_c0_src = c0_dir / "sources.parquet"

    write_parquet_table(
        pa.Table.from_arrays(
            [pa.array(["G1", "G2", "G3"]), pa.array(["L1", "L2_old", "L3"])],
            schema=parent_schema,
        ),
        p_c0_grp,
    )
    write_parquet_table(
        pa.Table.from_arrays(
            [
                pa.array(["i1_1", "i1_2", "i2_old1", "i2_old2", "i3_1"]),
                pa.array(["G1", "G1", "G2", "G2", "G3"]),
                pa.array(["d1", "d2", "old_p1", "old_p2", "d3"]),
            ],
            schema=child_schema,
        ),
        p_c0_itm,
    )
    write_parquet_table(
        pa.Table.from_arrays(
            [pa.array(["G1", "G2", "G3"]), pa.array(["S1", "S1", "S2"])],
            schema=source_schema,
        ),
        p_c0_src,
    )

    m_c0 = DAGNodeManifest(
        snapshot_id="c0",
        kind="checkpoint",
        parents=(),
        checkpoint_anchor_id="c0",
        lineage_depth=0,
        created_at="2026-10-07T00:00:00Z",
        relations={
            "groups": (
                PartDescriptor(
                    "groups.parquet",
                    file_sha256(p_c0_grp),
                    3,
                    p_c0_grp.stat().st_size,
                ),
            ),
            "items": (
                PartDescriptor(
                    "items.parquet",
                    file_sha256(p_c0_itm),
                    5,
                    p_c0_itm.stat().st_size,
                ),
            ),
            "sources": (
                PartDescriptor(
                    "sources.parquet",
                    file_sha256(p_c0_src),
                    3,
                    p_c0_src.stat().st_size,
                ),
            ),
        },
        logical_fingerprint="fp0",
    )
    catalog.record_node(m_c0)
    catalog.write_pointer("main", "c0")

    # 2. Delta D1: appends G4 with 1 item, adds co-filer source to G1
    d1_dir = tmp_path / "d1"
    d1_dir.mkdir(parents=True)
    p_d1_grp = d1_dir / "groups.parquet"
    p_d1_itm = d1_dir / "items.parquet"
    p_d1_src = d1_dir / "sources.parquet"

    write_parquet_table(
        pa.Table.from_arrays(
            [pa.array(["G4"]), pa.array(["L4"])], schema=parent_schema
        ),
        p_d1_grp,
    )
    write_parquet_table(
        pa.Table.from_arrays(
            [pa.array(["i4_1"]), pa.array(["G4"]), pa.array(["d4"])],
            schema=child_schema,
        ),
        p_d1_itm,
    )
    write_parquet_table(
        pa.Table.from_arrays(
            [pa.array(["G4", "G1"]), pa.array(["S3", "S_COFILER"])],
            schema=source_schema,
        ),
        p_d1_src,
    )

    m_d1 = DAGNodeManifest(
        snapshot_id="d1",
        kind="delta",
        parents=(ParentRef("c0", catalog.get_manifest_sha256("c0") or ""),),
        checkpoint_anchor_id="c0",
        lineage_depth=1,
        created_at="2026-10-07T00:01:00Z",
        relations={
            "groups": (
                PartDescriptor(
                    "groups.parquet",
                    file_sha256(p_d1_grp),
                    1,
                    p_d1_grp.stat().st_size,
                ),
            ),
            "items": (
                PartDescriptor(
                    "items.parquet",
                    file_sha256(p_d1_itm),
                    1,
                    p_d1_itm.stat().st_size,
                ),
            ),
            "sources": (
                PartDescriptor(
                    "sources.parquet",
                    file_sha256(p_d1_src),
                    2,
                    p_d1_src.stat().st_size,
                ),
            ),
        },
        logical_fingerprint="fp1",
    )
    catalog.record_node(m_d1)
    catalog.write_pointer("main", "d1")

    # 3. Delta D2: G2 is refreshed with 2 new items replacing old items
    d2_dir = tmp_path / "d2"
    d2_dir.mkdir(parents=True)
    p_d2_grp = d2_dir / "groups.parquet"
    p_d2_itm = d2_dir / "items.parquet"

    write_parquet_table(
        pa.Table.from_arrays(
            [pa.array(["G2"]), pa.array(["L2_refreshed"])], schema=parent_schema
        ),
        p_d2_grp,
    )
    write_parquet_table(
        pa.Table.from_arrays(
            [
                pa.array(["i2_new1", "i2_new2"]),
                pa.array(["G2", "G2"]),
                pa.array(["new_p1", "new_p2"]),
            ],
            schema=child_schema,
        ),
        p_d2_itm,
    )

    m_d2 = DAGNodeManifest(
        snapshot_id="d2",
        kind="delta",
        parents=(ParentRef("d1", catalog.get_manifest_sha256("d1") or ""),),
        checkpoint_anchor_id="c0",
        lineage_depth=2,
        created_at="2026-10-07T00:02:00Z",
        relations={
            "groups": (
                PartDescriptor(
                    "groups.parquet",
                    file_sha256(p_d2_grp),
                    1,
                    p_d2_grp.stat().st_size,
                ),
            ),
            "items": (
                PartDescriptor(
                    "items.parquet",
                    file_sha256(p_d2_itm),
                    2,
                    p_d2_itm.stat().st_size,
                ),
            ),
        },
        logical_fingerprint="fp2",
    )
    catalog.record_node(m_d2)
    catalog.write_pointer("main", "d2")

    # 4. Compact D2 lineage into C1
    c1_staged = tmp_path / "stage_c1"
    compacted = compact_lineage(
        tmp_path,
        specs,
        tip_id="d2",
        new_snapshot_id="c1",
        staged_dir=c1_staged,
        publish=True,
    )

    assert compacted.snapshot_id == "c1"
    assert compacted.kind == "checkpoint"
    assert compacted.lineage_depth == 0
    assert compacted.checkpoint_anchor_id == "c1"
    assert compacted.relations["groups"][0].row_count == 4
    # G1 (2), G2 (2 new), G3 (1), G4 (1) = 6 active items; 2 old G2 items purged
    assert compacted.relations["items"][0].row_count == 6
    assert compacted.relations["sources"][0].row_count == 5

    # 5. Verify physical parquet rows on disk have purged masked entries
    compacted_items = read_parquet_table(
        tmp_path / "c1" / "items" / "part-00000.parquet"
    )
    assert compacted_items.num_rows == 6
    payloads = compacted_items.column("payload").to_pylist()
    assert "old_p1" not in payloads
    assert "old_p2" not in payloads
    assert "new_p1" in payloads
    assert "new_p2" in payloads

    ptr = read_pointer(tmp_path)
    assert ptr is not None and ptr["snapshot_id"] == "c1"
