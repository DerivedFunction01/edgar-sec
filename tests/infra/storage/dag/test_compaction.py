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
    write_manifest,
)
from edgar_sec.infra.storage.dag.publication import read_pointer
from edgar_sec.infra.storage.dag.spec import RelationSpec
from edgar_sec.infra.storage.parquet import write_parquet_table

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
    c0_manifest_path = c0_dir / "manifest.json"
    write_manifest(c0_manifest_path, c0_manifest)
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
    write_manifest(d1_dir / "manifest.json", d1_manifest)
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
    write_manifest(c0_dir / "manifest.json", c0_manifest)
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
    c0_manifest_path = c0_dir / "manifest.json"
    write_manifest(c0_manifest_path, c0_manifest)
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
