from pathlib import Path

import pyarrow as pa

from edgar_sec.domain.document_inventory.schemas import ENTRY_SCHEMA
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.compaction import compact_lineage
from edgar_sec.infra.storage.dag.manifest import (
    DAGNodeManifest,
    ParentRef,
    PartDescriptor,
)
from edgar_sec.infra.storage.parquet import (
    DEFAULT_ROW_GROUP_SIZE,
    read_parquet_table,
    write_parquet_table,
)
from edgar_sec.pipelines.document_inventory.snapshot.schema import (
    SNAPSHOT_ACCESSIONS_SCHEMA,
    SNAPSHOT_ACCESSION_SOURCES_SCHEMA,
)
from edgar_sec.pipelines.document_inventory.snapshot.specs import (
    INVENTORY_ACCESSION_SOURCES_SPEC,
    INVENTORY_ACCESSIONS_SPEC,
    INVENTORY_ENTRIES_SPEC,
    INVENTORY_RELATIONS,
)


def test_inventory_relation_specs_are_valid() -> None:
    assert len(INVENTORY_RELATIONS) == 3

    assert INVENTORY_ACCESSIONS_SPEC.name == "accessions"
    assert INVENTORY_ACCESSIONS_SPEC.primary_key == ("accession",)
    assert INVENTORY_ACCESSIONS_SPEC.entity_key == "accession"
    assert INVENTORY_ACCESSIONS_SPEC.merge_strategy == "upsert"
    assert INVENTORY_ACCESSIONS_SPEC.max_rows_per_part == DEFAULT_ROW_GROUP_SIZE

    assert INVENTORY_ENTRIES_SPEC.name == "entries"
    assert INVENTORY_ENTRIES_SPEC.primary_key == ("entry_id",)
    assert INVENTORY_ENTRIES_SPEC.entity_key == "accession"
    assert INVENTORY_ENTRIES_SPEC.merge_strategy == "scoped_mask"
    assert INVENTORY_ENTRIES_SPEC.parent_relation == "accessions"
    assert INVENTORY_ENTRIES_SPEC.parent_join_key == ("accession",)
    assert INVENTORY_ENTRIES_SPEC.max_rows_per_part == DEFAULT_ROW_GROUP_SIZE

    assert INVENTORY_ACCESSION_SOURCES_SPEC.name == "accession_sources"
    assert INVENTORY_ACCESSION_SOURCES_SPEC.primary_key == (
        "accession",
        "source_cik",
    )
    assert INVENTORY_ACCESSION_SOURCES_SPEC.entity_key == "source_cik"
    assert INVENTORY_ACCESSION_SOURCES_SPEC.merge_strategy == "upsert"
    assert INVENTORY_ACCESSION_SOURCES_SPEC.max_rows_per_part == DEFAULT_ROW_GROUP_SIZE


def test_inventory_relations_compaction_parity(tmp_path: Path) -> None:
    """Verify compaction parity and entry supersession with INVENTORY_RELATIONS."""
    catalog = DAGCatalog(tmp_path)

    # 1. Base C0: ACC1 with 2 entries, ACC2 with 2 entries (old)
    c0_dir = tmp_path / "c0"
    c0_dir.mkdir(parents=True)
    p_c0_acc = c0_dir / "accessions.parquet"
    p_c0_ent = c0_dir / "entries.parquet"
    p_c0_src = c0_dir / "accession_sources.parquet"

    write_parquet_table(
        pa.Table.from_pydict(
            {
                "accession": ["0001-24-001", "0001-24-002"],
                "filing_cik": ["0001", "0001"],
                "form": ["10-K", "10-Q"],
                "filing_date": ["2024-03-01", "2024-06-01"],
                "report_date": ["2023-12-31", "2024-03-31"],
                "bundle_url": ["b1", "b2"],
                "bundle_size": [1000, 2000],
                "index_url": ["i1", "i2"],
                "index_sha256": ["h1", "h2"],
                "first_indexed_by": ["r0", "r0"],
            },
            schema=SNAPSHOT_ACCESSIONS_SCHEMA,
        ),
        p_c0_acc,
    )
    write_parquet_table(
        pa.Table.from_pydict(
            {
                "entry_id": ["e1_1", "e1_2", "e2_old1", "e2_old2"],
                "accession": [
                    "0001-24-001",
                    "0001-24-001",
                    "0001-24-002",
                    "0001-24-002",
                ],
                "table_kind": ["doc", "doc", "doc", "doc"],
                "row_ordinal": [0, 1, 0, 1],
                "sequence": [1, 2, 1, 2],
                "document_type": ["10-K", "EX-31", "10-Q", "EX-31"],
                "document_label": ["Annual", "Cert", "Quarterly", "Cert"],
                "description": ["10-K", "EX-31", "10-Q (OLD)", "EX-31 (OLD)"],
                "filename": ["10k.htm", "ex31.htm", "10q_old.htm", "ex31_old.htm"],
                "href": ["10k.htm", "ex31.htm", "10q_old.htm", "ex31_old.htm"],
                "archive_url": ["a1", "a2", "a3_old", "a4_old"],
                "byte_size": [500, 200, 400, 150],
            },
            schema=ENTRY_SCHEMA,
        ),
        p_c0_ent,
    )
    write_parquet_table(
        pa.Table.from_pydict(
            {
                "accession": ["0001-24-001", "0001-24-002"],
                "source_cik": ["0001", "0001"],
                "first_seen_by": ["r0", "r0"],
            },
            schema=SNAPSHOT_ACCESSION_SOURCES_SCHEMA,
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
            "accessions": (
                PartDescriptor(
                    "accessions.parquet",
                    file_sha256(p_c0_acc),
                    2,
                    p_c0_acc.stat().st_size,
                ),
            ),
            "entries": (
                PartDescriptor(
                    "entries.parquet", file_sha256(p_c0_ent), 4, p_c0_ent.stat().st_size
                ),
            ),
            "accession_sources": (
                PartDescriptor(
                    "accession_sources.parquet",
                    file_sha256(p_c0_src),
                    2,
                    p_c0_src.stat().st_size,
                ),
            ),
        },
        logical_fingerprint="fp0",
    )
    catalog.record_node(m_c0)
    catalog.write_pointer("main", "c0")

    # 2. Delta D1: Refreshes ACC2 with 2 new entries, adds co-filer source on ACC1
    d1_dir = tmp_path / "d1"
    d1_dir.mkdir(parents=True)
    p_d1_acc = d1_dir / "accessions.parquet"
    p_d1_ent = d1_dir / "entries.parquet"
    p_d1_src = d1_dir / "accession_sources.parquet"

    write_parquet_table(
        pa.Table.from_pydict(
            {
                "accession": ["0001-24-002"],
                "filing_cik": ["0001"],
                "form": ["10-Q"],
                "filing_date": ["2024-06-01"],
                "report_date": ["2024-03-31"],
                "bundle_url": ["b2_v2"],
                "bundle_size": [2200],
                "index_url": ["i2_v2"],
                "index_sha256": ["h2_v2"],
                "first_indexed_by": ["r1"],
            },
            schema=SNAPSHOT_ACCESSIONS_SCHEMA,
        ),
        p_d1_acc,
    )
    write_parquet_table(
        pa.Table.from_pydict(
            {
                "entry_id": ["e2_new1", "e2_new2"],
                "accession": ["0001-24-002", "0001-24-002"],
                "table_kind": ["doc", "doc"],
                "row_ordinal": [0, 1],
                "sequence": [1, 2],
                "document_type": ["10-Q", "EX-31"],
                "document_label": ["Quarterly", "Cert"],
                "description": ["10-Q (NEW)", "EX-31 (NEW)"],
                "filename": ["10q_new.htm", "ex31_new.htm"],
                "href": ["10q_new.htm", "ex31_new.htm"],
                "archive_url": ["a3_new", "a4_new"],
                "byte_size": [450, 180],
            },
            schema=ENTRY_SCHEMA,
        ),
        p_d1_ent,
    )
    write_parquet_table(
        pa.Table.from_pydict(
            {
                "accession": ["0001-24-001"],
                "source_cik": ["000999"],
                "first_seen_by": ["r1"],
            },
            schema=SNAPSHOT_ACCESSION_SOURCES_SCHEMA,
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
            "accessions": (
                PartDescriptor(
                    "accessions.parquet",
                    file_sha256(p_d1_acc),
                    1,
                    p_d1_acc.stat().st_size,
                ),
            ),
            "entries": (
                PartDescriptor(
                    "entries.parquet", file_sha256(p_d1_ent), 2, p_d1_ent.stat().st_size
                ),
            ),
            "accession_sources": (
                PartDescriptor(
                    "accession_sources.parquet",
                    file_sha256(p_d1_src),
                    1,
                    p_d1_src.stat().st_size,
                ),
            ),
        },
        logical_fingerprint="fp1",
    )
    catalog.record_node(m_d1)
    catalog.write_pointer("main", "d1")

    # 3. Compact D1 lineage into C1
    compacted = compact_lineage(
        tmp_path,
        INVENTORY_RELATIONS,
        tip_id="d1",
        new_snapshot_id="c1",
        staged_dir=tmp_path / "stage_c1",
        publish=True,
    )

    assert compacted.snapshot_id == "c1"
    assert compacted.relations["accessions"][0].row_count == 2
    # Active entries: ACC1 has 2, ACC2 has 2 new -> 4 rows total. 2 old rows purged!
    assert compacted.relations["entries"][0].row_count == 4
    # Sources: (ACC1, 0001), (ACC1, 000999), (ACC2, 0001) = 3 rows
    assert compacted.relations["accession_sources"][0].row_count == 3

    # 4. Verify physical parquet file on disk
    compacted_entries = read_parquet_table(
        tmp_path / "c1" / "entries" / "part-00000.parquet"
    )
    assert compacted_entries.num_rows == 4
    filenames = compacted_entries.column("filename").to_pylist()
    assert "10q_old.htm" not in filenames
    assert "10q_new.htm" in filenames
