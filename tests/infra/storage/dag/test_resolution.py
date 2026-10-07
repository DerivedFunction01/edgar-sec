"""Tests for dynamic DuckDB virtual view compilation and fingerprinting."""

from pathlib import Path

import pyarrow as pa

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.dag.manifest import (
    DAGNodeManifest,
    ParentRef,
    PartDescriptor,
    write_manifest,
)
from edgar_sec.infra.storage.dag.resolution import (
    compile_virtual_views,
    compute_logical_fingerprint,
)
from edgar_sec.infra.storage.dag.spec import RelationSpec
from edgar_sec.infra.storage.dag.traversal import walk_lineage
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.infra.storage.parquet import write_parquet_table

ACC_SCHEMA = pa.schema([("accession", pa.string()), ("form", pa.string())])
TARGET_SCHEMA = pa.schema(
    [
        ("accession", pa.string()),
        ("request_id", pa.string()),
        ("doc_path", pa.string()),
    ]
)


def test_upsert_and_composite_scoped_mask(tmp_path: Path) -> None:
    specs = (
        RelationSpec(
            name="accessions",
            schema=ACC_SCHEMA,
            primary_key=("accession",),
            merge_strategy="upsert",
            sort_order=("accession",),
        ),
        RelationSpec(
            name="targets",
            schema=TARGET_SCHEMA,
            primary_key=("accession", "request_id"),
            merge_strategy="scoped_mask",
            sort_order=("accession", "request_id"),
            parent_relation="accessions",
            parent_join_key=("accession",),
        ),
    )

    # 1. Base Checkpoint C0: Accession 001 with primary doc
    c0_dir = tmp_path / "c0"
    c0_dir.mkdir(parents=True)
    c0_acc_file = c0_dir / "acc.parquet"
    write_parquet_table(
        pa.Table.from_arrays(
            [pa.array(["acc-1"]), pa.array(["10-K"])], schema=ACC_SCHEMA
        ),
        c0_acc_file,
    )
    c0_tgt_file = c0_dir / "tgt.parquet"
    write_parquet_table(
        pa.Table.from_arrays(
            [
                pa.array(["acc-1"]),
                pa.array(["primary"]),
                pa.array(["primary_v1.htm"]),
            ],
            schema=TARGET_SCHEMA,
        ),
        c0_tgt_file,
    )

    c0_manifest = DAGNodeManifest(
        snapshot_id="c0",
        kind="checkpoint",
        parents=(),
        checkpoint_anchor_id="c0",
        lineage_depth=0,
        created_at="2026-10-07T00:00:00Z",
        relations={
            "accessions": (
                PartDescriptor(
                    "acc.parquet",
                    file_sha256(c0_acc_file),
                    1,
                    c0_acc_file.stat().st_size,
                ),
            ),
            "targets": (
                PartDescriptor(
                    "tgt.parquet",
                    file_sha256(c0_tgt_file),
                    1,
                    c0_tgt_file.stat().st_size,
                ),
            ),
        },
        logical_fingerprint="fp0",
    )
    c0_manifest_path = c0_dir / "manifest.json"
    write_manifest(c0_manifest_path, c0_manifest)

    # 2. Delta D1: Refresh Accession 001 with primary_v2.htm
    d1_dir = tmp_path / "d1"
    d1_dir.mkdir(parents=True)
    d1_acc_file = d1_dir / "acc.parquet"
    write_parquet_table(
        pa.Table.from_arrays(
            [pa.array(["acc-1"]), pa.array(["10-K"])], schema=ACC_SCHEMA
        ),
        d1_acc_file,
    )
    d1_tgt_file = d1_dir / "tgt.parquet"
    write_parquet_table(
        pa.Table.from_arrays(
            [
                pa.array(["acc-1"]),
                pa.array(["primary"]),
                pa.array(["primary_v2.htm"]),
            ],
            schema=TARGET_SCHEMA,
        ),
        d1_tgt_file,
    )

    d1_manifest = DAGNodeManifest(
        snapshot_id="d1",
        kind="delta",
        parents=(ParentRef("c0", file_sha256(c0_manifest_path)),),
        checkpoint_anchor_id="c0",
        lineage_depth=1,
        created_at="2026-10-07T00:01:00Z",
        relations={
            "accessions": (
                PartDescriptor(
                    "acc.parquet",
                    file_sha256(d1_acc_file),
                    1,
                    d1_acc_file.stat().st_size,
                ),
            ),
            "targets": (
                PartDescriptor(
                    "tgt.parquet",
                    file_sha256(d1_tgt_file),
                    1,
                    d1_tgt_file.stat().st_size,
                ),
            ),
        },
        logical_fingerprint="fp1",
    )
    write_manifest(d1_dir / "manifest.json", d1_manifest)

    # Resolve views
    lineage = walk_lineage(tmp_path, "d1")
    con = connect()
    try:
        compile_virtual_views(con, specs, lineage, tmp_path)
        active_tgt = con.execute(
            "SELECT doc_path FROM active_targets WHERE accession = 'acc-1' AND request_id = 'primary'"
        ).fetchall()
        # Primary v2 masked primary v1
        assert active_tgt == [("primary_v2.htm",)]

        fingerprint = compute_logical_fingerprint(con, specs)
        assert len(fingerprint) == 64
    finally:
        con.close()
