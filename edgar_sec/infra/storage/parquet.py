"""Parquet read/write operations with atomic serialization and zstd compression."""

from __future__ import annotations

import os

import pyarrow as pa
import pyarrow.parquet as pq

from .atomic import _fsync_dir

DEFAULT_ROW_GROUP_SIZE = 128_000
DEFAULT_COMPRESSION = "zstd"


def write_parquet_table(
    table: pa.Table,
    path: str | os.PathLike[str],
    *,
    compression: str = DEFAULT_COMPRESSION,
    row_group_size: int = DEFAULT_ROW_GROUP_SIZE,
) -> int:
    """Atomically serialize PyArrow Table to a Parquet file."""
    path_str = os.fspath(path)
    directory = os.path.dirname(os.path.abspath(path_str))
    os.makedirs(directory, exist_ok=True)
    tmp_path = f"{path_str}.tmp.{os.getpid()}"
    try:
        pq.write_table(
            table,
            tmp_path,
            compression=compression,
            row_group_size=row_group_size,
        )
        os.replace(tmp_path, path_str)
        _fsync_dir(directory)
        return table.num_rows
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def read_parquet_schema(path: str | os.PathLike[str]) -> pa.Schema:
    """Read schema from Parquet file footer without loading record batches."""
    return pq.read_schema(path)


def count_parquet_rows(path: str | os.PathLike[str]) -> int:
    """Return total row count directly from Parquet metadata footer."""
    metadata = pq.read_metadata(path)
    return metadata.num_rows


def read_parquet_table(
    path: str | os.PathLike[str],
    columns: list[str] | None = None,
) -> pa.Table:
    """Read Parquet file into PyArrow Table with optional column projection."""
    return pq.read_table(path, columns=columns)


__all__ = [
    "DEFAULT_COMPRESSION",
    "DEFAULT_ROW_GROUP_SIZE",
    "count_parquet_rows",
    "read_parquet_schema",
    "read_parquet_table",
    "write_parquet_table",
]
