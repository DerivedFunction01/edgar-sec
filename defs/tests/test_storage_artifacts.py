from __future__ import annotations

import json

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from defs.storage import DatasetSpec, read_records
from defs.storage.errors import MalformedArtifact

SCHEMA = pa.schema(
    [
        ("cik", pa.string()),
        ("name", pa.string()),
        ("status", pa.string()),
    ]
)
SPEC = DatasetSpec(
    name="test_records",
    schema_version="1.0.0",
    key_field="cik",
    arrow_schema=SCHEMA,
    required_fields=("cik", "status"),
)

ROWS = [
    {"cik": "0000000020", "name": "ACME", "status": "ok"},
    {"cik": "0000000021", "name": "BETA", "status": "failed"},
]


def _write_parquet(path, rows):
    pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), str(path))


def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        fh.writelines(json.dumps(row) + "\n" for row in rows)


def test_read_records_parquet_validates_schema(tmp_path):
    path = tmp_path / "data.parquet"
    _write_parquet(path, ROWS)
    assert read_records(str(path), "parquet", spec=SPEC) == ROWS


def test_read_records_jsonl_validates_schema(tmp_path):
    path = tmp_path / "data.jsonl"
    _write_jsonl(path, ROWS)
    assert read_records(str(path), "jsonl", spec=SPEC) == ROWS


def test_read_records_rejects_malformed_jsonl(tmp_path):
    path = tmp_path / "data.jsonl"
    path.write_text("{not valid json}\n", encoding="utf-8")
    with pytest.raises(MalformedArtifact):
        read_records(str(path), "jsonl", spec=SPEC)


def test_read_records_rejects_schema_violation(tmp_path):
    path = tmp_path / "data.jsonl"
    _write_jsonl(
        path,
        [{"cik": "0000000020", "name": "ACME", "status": "ok", "extra": "nope"}],
    )
    with pytest.raises(MalformedArtifact):
        read_records(str(path), "jsonl", spec=SPEC)
