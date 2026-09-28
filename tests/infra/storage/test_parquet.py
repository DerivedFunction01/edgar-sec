"""Unit tests for infra.storage.parquet."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa

from edgar_sec.infra.storage.parquet import (
    count_parquet_rows,
    read_parquet_schema,
    read_parquet_table,
    write_parquet_table,
)

SCHEMA = pa.schema([("cik", pa.string()), ("val", pa.int64())])


def _table(ciks: list[str], values: list[int]) -> pa.Table:
    return pa.Table.from_arrays([pa.array(ciks), pa.array(values)], schema=SCHEMA)


def test_write_read_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "chunk.parquet"
    write_parquet_table(_table(["b", "a"], [2, 1]), path)

    assert path.is_file()
    assert count_parquet_rows(path) == 2
    assert read_parquet_schema(path) == SCHEMA

    table = read_parquet_table(path)
    assert table.column("cik").to_pylist() == ["b", "a"]


def test_read_parquet_table_column_projection(tmp_path: Path) -> None:
    path = tmp_path / "chunk.parquet"
    write_parquet_table(_table(["a"], [1]), path)
    table = read_parquet_table(path, columns=["cik"])
    assert table.column_names == ["cik"]
    assert table.column("cik").to_pylist() == ["a"]
