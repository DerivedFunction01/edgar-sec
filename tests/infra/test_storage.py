"""Unit tests for storage infrastructure: atomic writes, Parquet, and DuckDB."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa

from edgar_sec.infra.storage.atomic import (
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
)
from edgar_sec.infra.storage.duckdb import (
    concat_to_parquet,
    connect,
    find_duplicate_keys,
    find_null_keys,
)
from edgar_sec.infra.storage.parquet import (
    count_parquet_rows,
    read_parquet_schema,
    read_parquet_table,
    write_parquet_table,
)


def test_atomic_file_writes(tmp_path: Path) -> None:
    text_file = tmp_path / "sample.txt"
    bytes_written = atomic_write_text(text_file, "hello atomic world")
    assert bytes_written > 0
    assert text_file.read_text(encoding="utf-8") == "hello atomic world"

    bin_file = tmp_path / "sample.bin"
    atomic_write_bytes(bin_file, b"\x00\x01\x02\x03")
    assert bin_file.read_bytes() == b"\x00\x01\x02\x03"

    json_file = tmp_path / "sample.json"
    atomic_write_json(json_file, {"b": 2, "a": 1})
    assert json_file.read_text(encoding="utf-8") == '{"a":1,"b":2}'


def test_parquet_and_duckdb_concat(tmp_path: Path) -> None:
    schema = pa.schema([("cik", pa.string()), ("val", pa.int64())])

    t1 = pa.Table.from_arrays(
        [pa.array(["0000000002", "0000000001"]), pa.array([20, 10])], schema=schema
    )
    t2 = pa.Table.from_arrays(
        [pa.array(["0000000004", "0000000003"]), pa.array([40, 30])], schema=schema
    )

    f1 = tmp_path / "chunk1.parquet"
    f2 = tmp_path / "chunk2.parquet"
    write_parquet_table(t1, f1)
    write_parquet_table(t2, f2)

    assert count_parquet_rows(f1) == 2
    assert count_parquet_rows(f2) == 2
    assert read_parquet_schema(f1) == schema

    con = connect()
    out_parquet = tmp_path / "merged.parquet"
    total_rows = concat_to_parquet(con, [f1, f2], out_parquet, order_by=["cik"])
    assert total_rows == 4

    merged_table = read_parquet_table(out_parquet)
    ciks = merged_table.column("cik").to_pylist()
    assert ciks == ["0000000001", "0000000002", "0000000003", "0000000004"]

    # Verify duplicate and null key detection
    dups = find_duplicate_keys(con, [f1, f2], key_column="cik")
    assert dups == []
    nulls = find_null_keys(con, [f1, f2], key_column="cik")
    assert nulls == 0
