"""Contract tests for FinalizedDataset and multi-part snapshot reader."""

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from defs.runtime.artifacts import make_snapshot_manifest, publish_snapshot_manifest
from defs.storage import FinalizedDataset, StorageError, file_sha256


def _write_parquet(path: Path, records: list[dict], schema: pa.Schema) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(records, schema=schema)
    pq.write_table(table, str(path), compression="zstd")
    return file_sha256(str(path))


def test_finalized_dataset_single_parquet(tmp_path):
    schema = pa.schema(
        [
            ("cik", pa.string()),
            ("name", pa.string()),
        ]
    )
    part_path = tmp_path / "part-000.parquet"
    records = [
        {"cik": "0000000020", "name": "K TRON"},
        {"cik": "0000001761", "name": "TRANZONIC"},
    ]
    _write_parquet(part_path, records, schema)

    with FinalizedDataset(part_path) as dataset:
        assert dataset.columns == ["cik", "name"]
        assert dataset.count() == 2
        assert dataset.distinct_values("cik") == {"0000000020", "0000001761"}
        rows = dataset.run(f"SELECT name FROM {dataset.relation} ORDER BY cik")
        assert rows == [("K TRON",), ("TRANZONIC",)]

        out_copy = tmp_path / "copy.parquet"
        copied = dataset.copy_query(
            f"SELECT * FROM {dataset.relation} WHERE cik = '0000000020'", out_copy
        )
        assert copied == 1
        assert out_copy.is_file()


def test_finalized_dataset_multi_part_snapshot(tmp_path):
    schema = pa.schema(
        [
            ("cik", pa.string()),
            ("name", pa.string()),
        ]
    )
    root = tmp_path / "artifacts"
    parts_dir = (
        root
        / "manifests"
        / "metadata"
        / "submission_metadata"
        / "snapshots"
        / "S0"
        / "parts"
    )

    part1 = parts_dir / "shard-0000" / "part-000.parquet"
    part2 = parts_dir / "shard-0001" / "part-000.parquet"

    hash1 = _write_parquet(part1, [{"cik": "0000000020", "name": "K TRON"}], schema)
    hash2 = _write_parquet(part2, [{"cik": "0000001761", "name": "TRANZONIC"}], schema)

    manifest_data = make_snapshot_manifest(
        snapshot_id="S0",
        schema_version="1.0.0",
        resolved_parts=[
            {
                "path": str(part1.relative_to(root)),
                "artifact_sha256": hash1,
                "row_count": 1,
            },
            {
                "path": str(part2.relative_to(root)),
                "artifact_sha256": hash2,
                "row_count": 1,
            },
        ],
    )
    manifest_path = publish_snapshot_manifest(
        manifest_data, artifacts_root=root, set_current=True
    )
    assert manifest_path.is_file()

    with FinalizedDataset(manifest_path, artifacts_root=root) as dataset:
        assert dataset.snapshot_id == "S0"
        assert dataset.columns == ["cik", "name"]
        assert dataset.count() == 2
        assert dataset.distinct_values("cik") == {"0000000020", "0000001761"}

    # Open by directory
    with FinalizedDataset(manifest_path.parent, artifacts_root=root) as dataset:
        assert dataset.count() == 2


def test_finalized_dataset_replacement_anti_join(tmp_path):
    schema = pa.schema(
        [
            ("cik", pa.string()),
            ("name", pa.string()),
        ]
    )
    key_schema = pa.schema(
        [
            ("cik", pa.string()),
        ]
    )
    root = tmp_path / "artifacts"
    s0_dir = (
        root
        / "manifests"
        / "metadata"
        / "submission_metadata"
        / "snapshots"
        / "S0"
        / "parts"
    )
    s1_dir = (
        root / "manifests" / "metadata" / "submission_metadata" / "snapshots" / "S1"
    )

    # S0 has 2 CIKs
    s0_part = s0_dir / "shard-0000" / "part-000.parquet"
    s0_hash = _write_parquet(
        s0_part,
        [
            {"cik": "0000000020", "name": "K TRON OLD"},
            {"cik": "0000001761", "name": "TRANZONIC UNCHANGED"},
        ],
        schema,
    )

    # S1 replaces CIK 20 and adds CIK 37996
    s1_part = s1_dir / "parts" / "shard-0000" / "part-000.parquet"
    s1_hash = _write_parquet(
        s1_part,
        [
            {"cik": "0000000020", "name": "K TRON REFRESHED"},
            {"cik": "0000037996", "name": "FORD MOTOR NEW"},
        ],
        schema,
    )

    # Replacement key part for CIK 20
    key_part = s1_dir / "replacement-keys" / "keys-000.parquet"
    key_hash = _write_parquet(key_part, [{"cik": "0000000020"}], key_schema)

    s1_manifest = make_snapshot_manifest(
        snapshot_id="S1",
        parent_snapshot_id="S0",
        schema_version="1.0.0",
        resolved_parts=[
            {
                "path": str(s0_part.relative_to(root)),
                "artifact_sha256": s0_hash,
                "row_count": 2,
            },
            {
                "path": str(s1_part.relative_to(root)),
                "artifact_sha256": s1_hash,
                "row_count": 2,
            },
        ],
        added_parts=[
            {
                "path": str(s1_part.relative_to(root)),
                "artifact_sha256": s1_hash,
                "row_count": 2,
            }
        ],
        replacement_key_parts=[
            {
                "path": str(key_part.relative_to(root)),
                "artifact_sha256": key_hash,
                "key_count": 1,
            }
        ],
        effective_cik_count=3,
    )
    manifest_path = publish_snapshot_manifest(
        s1_manifest, artifacts_root=root, set_current=True
    )

    with FinalizedDataset(manifest_path, artifacts_root=root) as dataset:
        assert dataset.count() == 3
        rows = sorted(dataset.run(f"SELECT cik, name FROM {dataset.relation}"))
        assert rows == [
            ("0000000020", "K TRON REFRESHED"),
            ("0000001761", "TRANZONIC UNCHANGED"),
            ("0000037996", "FORD MOTOR NEW"),
        ]


def test_finalized_dataset_register_function(tmp_path):
    schema = pa.schema([("cik", pa.string())])
    part = tmp_path / "part.parquet"
    _write_parquet(part, [{"cik": "20"}], schema)

    with FinalizedDataset(part) as dataset:
        dataset.register_function(
            "pad_cik",
            lambda val: str(val).zfill(10),
            parameters=[str],
            return_type=str,
        )
        rows = dataset.run(f"SELECT pad_cik(cik) FROM {dataset.relation}")
        assert rows == [("0000000020",)]


def test_finalized_dataset_errors(tmp_path):
    with pytest.raises(StorageError):
        FinalizedDataset(tmp_path / "nonexistent.parquet")

    empty_manifest = tmp_path / "empty.json"
    empty_manifest.write_text('{"manifest_kind": "test", "resolved_parts": []}')
    with pytest.raises(StorageError):
        FinalizedDataset(empty_manifest)


def test_list_and_next_snapshot_id(tmp_path):
    from defs.runtime.artifacts import list_snapshots, next_snapshot_id

    root = tmp_path / "artifacts"
    assert next_snapshot_id(phase="metadata", dataset="submission_metadata", artifacts_root=root) == "S0"
    assert list_snapshots(phase="metadata", dataset="submission_metadata", artifacts_root=root) == []

    # Publish S0
    s0_manifest = make_snapshot_manifest(
        snapshot_id="S0",
        schema_version="1.0.0",
        resolved_parts=[],
        effective_cik_count=100,
    )
    publish_snapshot_manifest(s0_manifest, artifacts_root=root, set_current=True)
    assert next_snapshot_id(phase="metadata", dataset="submission_metadata", artifacts_root=root) == "S1"

    # Publish S1
    s1_manifest = make_snapshot_manifest(
        snapshot_id="S1",
        schema_version="1.0.0",
        resolved_parts=[],
        parent_snapshot_id="S0",
        effective_cik_count=150,
    )
    publish_snapshot_manifest(s1_manifest, artifacts_root=root, set_current=True)
    assert next_snapshot_id(phase="metadata", dataset="submission_metadata", artifacts_root=root) == "S2"

    snaps = list_snapshots(phase="metadata", dataset="submission_metadata", artifacts_root=root)
    assert len(snaps) == 2
    assert [s["snapshot_id"] for s in snaps] == ["S0", "S1"]
    assert snaps[1]["parent_snapshot_id"] == "S0"

