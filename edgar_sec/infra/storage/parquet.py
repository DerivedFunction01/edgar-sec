"""Parquet read/write operations with atomic serialization and zstd compression."""

from __future__ import annotations

import os
import types
from pathlib import Path
from typing import Any, Self

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.foundation.runtime.settings.parquet import (
    resolve_row_group_size,
)

from .atomic import _fsync_dir

DEFAULT_COMPRESSION = "zstd"


def write_parquet_table(
    table: pa.Table,
    path: str | os.PathLike[str],
    *,
    compression: str = DEFAULT_COMPRESSION,
    row_group_size: int | None = None,
) -> int:
    effective_row_group_size = resolve_row_group_size(row_group_size)
    path_str = os.fspath(path)
    directory = os.path.dirname(os.path.abspath(path_str))
    os.makedirs(directory, exist_ok=True)
    tmp_path = f"{path_str}.tmp.{os.getpid()}"
    try:
        pq.write_table(
            table,
            tmp_path,
            compression=compression,
            row_group_size=effective_row_group_size,
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


def read_parquet_key_bounds(
    path: str | os.PathLike[str],
    column: str,
) -> tuple[str | None, str | None]:
    """Extract column min/max bounds from Parquet footer metadata or DuckDB."""
    parquet = pq.ParquetFile(path)
    schema = parquet.schema_arrow
    idx = schema.get_field_index(column)
    if idx < 0:
        return None, None
    meta = parquet.metadata
    mins, maxs = [], []
    for rg in range(meta.num_row_groups):
        stat = meta.row_group(rg).column(idx).statistics
        if stat is not None and stat.has_min_max:
            mins.append(str(stat.min))
            maxs.append(str(stat.max))
    if mins and maxs:
        return min(mins), max(maxs)
    from .duckdb import connect, sql_identifier

    con = connect()
    try:
        res = con.execute(
            f"SELECT min({sql_identifier(column)}), max({sql_identifier(column)}) FROM read_parquet(?)",
            [str(path)],
        ).fetchone()
        return (
            str(res[0]) if res[0] is not None else None,
            str(res[1]) if res[1] is not None else None,
        )
    finally:
        con.close()


class StagedParquetWriter:
    """Atomic, incremental Parquet writer for streaming chunk checkpoints.

    Writes stage to a sibling ``.tmp``; promoting it is an atomic ``os.replace`` plus a
    directory fsync. Committed key IDs are readable for intra-chunk resumption.
    """

    def __init__(
        self,
        final_path: str | os.PathLike[str],
        schema: pa.Schema,
        *,
        compression: str = DEFAULT_COMPRESSION,
        row_group_size: int | None = None,
        id_column: str | None = None,
        preserve_on_error: bool = False,
    ) -> None:
        self.final_path = Path(final_path).resolve()
        self.tmp_path = self.final_path.with_name(f"{self.final_path.name}.tmp")
        self.schema = schema
        self.compression = compression
        self.row_group_size = resolve_row_group_size(row_group_size)
        self.id_column = id_column
        self.preserve_on_error = preserve_on_error
        self._writer: pq.ParquetWriter | None = None
        self._row_count: int = 0
        self._closed: bool = False
        self._preloaded_table: pa.Table | None = None

    @property
    def row_count(self) -> int:
        return self._row_count

    def get_existing_ids(self) -> set[str]:
        """Read committed primary key IDs from an existing .tmp file for partial resumption.

        A readable, schema-matching ``.tmp`` has its rows preloaded; a corrupted one is reset.
        """
        if not self.tmp_path.is_file() or not self.id_column:
            return set()
        try:
            actual_schema = pq.read_schema(self.tmp_path)
            if self.id_column not in actual_schema.names:
                self.reset()
                return set()
            table = pq.read_table(self.tmp_path)
            if table.schema != self.schema:
                self.reset()
                return set()
            self._preloaded_table = table
            ids = set(table.column(self.id_column).to_pylist())
            return {str(x) for x in ids if x is not None}
        except (OSError, pa.ArrowInvalid, pq.ParquetException):
            self.reset()
            return set()

    def reset(self) -> None:
        """Remove the staging .tmp file and reset in-memory state."""
        if self._writer is not None:
            try:
                self._writer.close()
            except (OSError, pa.ArrowInvalid, pq.ParquetException):
                pass
            self._writer = None
        if self.tmp_path.is_file():
            try:
                self.tmp_path.unlink()
            except OSError:
                pass
        self._row_count = 0
        self._closed = False
        self._preloaded_table = None

    def _ensure_writer(self) -> pq.ParquetWriter:
        if self._writer is None:
            self.tmp_path.parent.mkdir(parents=True, exist_ok=True)
            self._writer = pq.ParquetWriter(
                str(self.tmp_path),
                self.schema,
                compression=self.compression,
            )
            if self._preloaded_table is not None and self._preloaded_table.num_rows > 0:
                self._writer.write_table(
                    self._preloaded_table, row_group_size=self.row_group_size
                )
                self._row_count += self._preloaded_table.num_rows
                self._preloaded_table = None
        return self._writer

    def write_batch(
        self,
        batch: pa.RecordBatch | pa.Table | dict[str, list[Any]],
    ) -> int:
        """Incrementally append a batch to the staging .tmp Parquet file."""
        if self._closed:
            raise RuntimeError("cannot write to a closed StagedParquetWriter")

        writer = self._ensure_writer()
        if isinstance(batch, dict):
            table = pa.Table.from_pydict(batch, schema=self.schema)
            writer.write_table(table, row_group_size=self.row_group_size)
            num_rows = table.num_rows
        elif isinstance(batch, pa.RecordBatch):
            writer.write_batch(batch)
            num_rows = batch.num_rows
        elif isinstance(batch, pa.Table):
            writer.write_table(batch, row_group_size=self.row_group_size)
            num_rows = batch.num_rows
        else:
            raise TypeError(f"unsupported batch type: {type(batch)}")

        self._row_count += num_rows
        return num_rows

    def commit(self, expected_count: int | None = None) -> int:
        """Close writer, validate row count, atomically rename .tmp -> final, and fsync."""
        if self._closed:
            return self._row_count

        if self._writer is None and not self.tmp_path.is_file():
            # Nothing was written yet (e.g. empty chunk); create valid empty Parquet file
            self._ensure_writer()

        if self._writer is not None:
            self._writer.close()
            self._writer = None
        elif self._preloaded_table is not None:
            self._ensure_writer()
            assert self._writer is not None
            self._writer.close()
            self._writer = None

        self._closed = True

        if not self.tmp_path.is_file():
            raise FileNotFoundError(f"staging file {self.tmp_path} does not exist")

        actual_rows = count_parquet_rows(self.tmp_path)
        if expected_count is not None and actual_rows != expected_count:
            raise ValueError(
                f"staged chunk row count mismatch for {self.final_path.name}: "
                f"expected {expected_count}, got {actual_rows}"
            )

        os.replace(self.tmp_path, self.final_path)
        _fsync_dir(str(self.final_path.parent))
        return actual_rows

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        if exc_type is not None:
            if self.preserve_on_error:
                # A readable stage is resumable; an unreadable one is
                # rejected and reset by the next get_existing_ids().
                if self._writer is not None:
                    try:
                        self._writer.close()
                    except (OSError, pa.ArrowInvalid, pq.ParquetException):
                        pass
                    self._writer = None
            else:
                self.reset()
        elif not self._closed and self._writer is not None:
            self._writer.close()
            self._writer = None


__all__ = [
    "DEFAULT_COMPRESSION",
    "StagedParquetWriter",
    "count_parquet_rows",
    "read_parquet_key_bounds",
    "read_parquet_schema",
    "read_parquet_table",
    "write_parquet_table",
]
