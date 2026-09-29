"""Unit tests for infra.storage.parquet."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pytest

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


# ------------------------------------------------------------------ atomicity
#
# Chunk checkpoints are the resumability contract: a partially written checkpoint
# that looked complete would let a truncated fetch be merged as a finished chunk.
# The write therefore stages to a sibling temp file and renames, and these tests
# pin that property rather than trusting it.


def test_write_parquet_table_leaves_no_temp_file(tmp_path: Path) -> None:
    path = tmp_path / "chunk.parquet"
    write_parquet_table(_table(["a"], [1]), path)
    assert [item.name for item in tmp_path.iterdir()] == ["chunk.parquet"]


def test_write_parquet_table_replaces_atomically(tmp_path: Path) -> None:
    """A rewrite is a rename, so a reader never observes a partial file."""
    path = tmp_path / "chunk.parquet"
    write_parquet_table(_table(["a"], [1]), path)
    write_parquet_table(_table(["b", "c"], [2, 3]), path)

    assert count_parquet_rows(path) == 2
    assert read_parquet_table(path).column("cik").to_pylist() == ["b", "c"]
    assert [item.name for item in tmp_path.iterdir()] == ["chunk.parquet"]


def test_a_failed_write_preserves_the_previous_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "chunk.parquet"
    write_parquet_table(_table(["a"], [1]), path)

    def explode(*_args, **_kwargs) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("pyarrow.parquet.write_table", explode)
    with pytest.raises(OSError):
        write_parquet_table(_table(["b"], [2]), path)

    # The prior checkpoint survives intact and no temp file is left behind.
    assert read_parquet_table(path).column("cik").to_pylist() == ["a"]
    assert [item.name for item in tmp_path.iterdir()] == ["chunk.parquet"]


def test_a_temp_checkpoint_is_never_discovered_as_complete(tmp_path: Path) -> None:
    """A crashed writer's ``.tmp.<pid>`` sibling must not look like a chunk."""
    import glob

    path = tmp_path / "chunk_0000.parquet"
    write_parquet_table(_table(["a"], [1]), path)
    (tmp_path / "chunk_0001.parquet.tmp.99999").write_bytes(b"partial")

    assert sorted(glob.glob(str(tmp_path / "chunk_*.parquet"))) == [str(path)]
