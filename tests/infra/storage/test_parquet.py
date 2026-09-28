"""Unit tests for infra.storage.parquet."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa

from edgar_sec.infra.storage.parquet import (
    DEFAULT_ROW_GROUP_SIZE,
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


def test_row_group_default_matches_the_catalog_setting() -> None:
    """The writer default and the catalog setting default must not drift.

    The two constants are declared separately because the settings module is
    Layer 0 and cannot import this Layer 2 writer under the enforced layer
    graph. This test is the substitute for that import.
    """
    from edgar_sec.foundation.runtime.settings.catalog import (
        DEFAULT_ROW_GROUP_SIZE as SETTING_ROW_GROUP_SIZE,
    )

    assert SETTING_ROW_GROUP_SIZE == DEFAULT_ROW_GROUP_SIZE


def test_duckdb_copy_helper_inherits_the_same_row_group_default() -> None:
    """The SQL COPY path must use the same row group size as the Arrow writer."""
    import inspect

    from edgar_sec.infra.storage.duckdb_catalog import copy_query_to_parquet

    default = inspect.signature(copy_query_to_parquet).parameters["row_group_size"]
    assert default.default == DEFAULT_ROW_GROUP_SIZE
