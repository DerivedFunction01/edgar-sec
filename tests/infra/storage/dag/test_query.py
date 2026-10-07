"""Tests for DAG point lookup and range pruning query engine."""

from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.infra.storage.dag.manifest import (
    DAGNodeManifest,
    ParentRef,
    PartDescriptor,
    write_manifest,
)
from edgar_sec.infra.storage.dag.query import (
    compile_pruned_views,
    derive_accession_range,
    prune_parts_for_range,
    query_point,
)
from edgar_sec.infra.storage.dag.spec import RelationSpec
from edgar_sec.infra.storage.dag.traversal import walk_lineage

SCHEMA = pa.schema(
    [
        ("accession", pa.string()),
        ("filing_cik", pa.string()),
        ("val", pa.int64()),
    ]
)

SPEC = RelationSpec(
    name="accessions",
    schema=SCHEMA,
    primary_key=("accession",),
    sort_order=("accession",),
    merge_strategy="upsert",
    entity_key="accession",
)


def _setup_multi_part_dag(tmp_path: Path) -> tuple[Path, str]:
    c0_dir = tmp_path / "c0"
    c0_dir.mkdir()
    p1 = c0_dir / "p1.parquet"
    p2 = c0_dir / "p2.parquet"

    t1 = pa.Table.from_pylist(
        [
            {"accession": "0000000001-25-000001", "filing_cik": "0000000001", "val": 1},
            {"accession": "0000000001-25-000002", "filing_cik": "0000000001", "val": 2},
        ],
        schema=SCHEMA,
    )
    pq.write_table(t1, p1)

    t2 = pa.Table.from_pylist(
        [
            {
                "accession": "0000000002-25-000001",
                "filing_cik": "0000000002",
                "val": 10,
            },
            {
                "accession": "0000000002-25-000002",
                "filing_cik": "0000000002",
                "val": 20,
            },
        ],
        schema=SCHEMA,
    )
    pq.write_table(t2, p2)

    c0_m = DAGNodeManifest(
        snapshot_id="c0",
        kind="checkpoint",
        parents=(),
        checkpoint_anchor_id="c0",
        lineage_depth=0,
        created_at="2026-01-01T00:00:00Z",
        relations={
            "accessions": (
                PartDescriptor(
                    "p1.parquet",
                    file_sha256(p1),
                    2,
                    p1.stat().st_size,
                    "0000000001-25-000001",
                    "0000000001-25-000002",
                ),
                PartDescriptor(
                    "p2.parquet",
                    file_sha256(p2),
                    2,
                    p2.stat().st_size,
                    "0000000002-25-000001",
                    "0000000002-25-000002",
                ),
            )
        },
        logical_fingerprint="fp0",
    )
    c0_man = c0_dir / "manifest.json"
    write_manifest(c0_man, c0_m)

    d1_dir = tmp_path / "d1"
    d1_dir.mkdir()
    p3 = d1_dir / "p3.parquet"
    t3 = pa.Table.from_pylist(
        [
            {
                "accession": "0000000001-25-000001",
                "filing_cik": "0000000001",
                "val": 999,
            },  # updated row
        ],
        schema=SCHEMA,
    )
    pq.write_table(t3, p3)

    d1_m = DAGNodeManifest(
        snapshot_id="d1",
        kind="delta",
        parents=(ParentRef("c0", file_sha256(c0_man)),),
        checkpoint_anchor_id="c0",
        lineage_depth=1,
        created_at="2026-01-01T00:01:00Z",
        relations={
            "accessions": (
                PartDescriptor(
                    "p3.parquet",
                    file_sha256(p3),
                    1,
                    p3.stat().st_size,
                    "0000000001-25-000001",
                    "0000000001-25-000001",
                ),
            )
        },
        logical_fingerprint="fp1",
    )
    write_manifest(d1_dir / "manifest.json", d1_m)
    return tmp_path, "d1"


def test_derive_accession_range() -> None:
    r_min, r_max = derive_accession_range("320193")
    assert r_min == "0000320193-00-000000"
    assert r_max == "0000320193-99-999999"


def test_prune_parts_for_range(tmp_path: Path) -> None:
    root, tip = _setup_multi_part_dag(tmp_path)
    lineage = walk_lineage(root, tip)

    # Key that only matches p1 and p3 (not p2)
    candidates = prune_parts_for_range(
        lineage, "accessions", "0000000001-25-000001", "0000000001-25-000001", root
    )
    names = [p.name for _, p in candidates]
    assert "p1.parquet" in names
    assert "p3.parquet" in names
    assert "p2.parquet" not in names


def test_query_point_upsert_precedence(tmp_path: Path) -> None:
    root, tip = _setup_multi_part_dag(tmp_path)
    lineage = walk_lineage(root, tip)
    con = connect()

    # Query accession that was updated in d1
    rows = query_point(con, SPEC, lineage, root, "0000000001-25-000001")
    assert len(rows) == 1
    assert rows[0]["val"] == 999  # delta update won over c0


def test_query_point_by_filing_cik(tmp_path: Path) -> None:
    root, tip = _setup_multi_part_dag(tmp_path)
    lineage = walk_lineage(root, tip)
    con = connect()

    # Query by filing_cik with automatic accession range derivation
    rows = query_point(con, SPEC, lineage, root, "0000000002", key_column="filing_cik")
    assert len(rows) == 2
    assert {r["accession"] for r in rows} == {
        "0000000002-25-000001",
        "0000000002-25-000002",
    }
