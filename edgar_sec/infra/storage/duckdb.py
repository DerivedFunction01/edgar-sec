"""Managed DuckDB connection factory and out-of-core Parquet serialization.

Mandates machine-derived resource limits to prevent out-of-memory errors on large merges.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb
import pyarrow as pa

if TYPE_CHECKING:
    from edgar_sec.foundation.runtime.resources import RuntimeResourceProfile

from .atomic import _fsync_dir
from .parquet import (
    DEFAULT_COMPRESSION,
    cast_table,
    count_parquet_rows,
    rewrite_parquet_schema,
)
from edgar_sec.foundation.runtime.settings.parquet import resolve_row_group_size
from edgar_sec.foundation.runtime.settings.runtime import resolve_read_batch_size

# The only DuckDB names other modules may use, served from this leaf module so
# no other file imports duckdb: a version rename lands here alone.
Connection = duckdb.DuckDBPyConnection
Relation = duckdb.DuckDBPyRelation
DuckDBError = duckdb.Error
InvalidInputError = duckdb.InvalidInputException

#: File databases are written at the 1.5 storage line while both supported
#: DuckDB versions must read each other's files.
STORAGE_COMPATIBILITY_VERSION = "v1.5.0"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def sql_literal(value: str) -> str:
    """Return ``value`` as a single-quoted SQL string literal.

    Embedded single quotes are doubled, which is the SQL-standard escape.
    """
    return "'" + str(value).replace("'", "''") + "'"


def sql_identifier(name: str) -> str:
    """Return ``name`` if it is a dotted path of bare SQL identifiers, else raise.

    An ``alias.`` prefix is accepted so a predicate reused in a joined query can still
    name its column; each segment is validated independently.
    """
    if not name or not all(
        _IDENTIFIER_RE.match(segment) for segment in name.split(".")
    ):
        raise ValueError(f"unsafe SQL identifier: {name!r}")
    return name


def sql_quoted_identifier(name: str) -> str:
    """Return ``name`` with each dotted segment double-quoted, else raise.

    Reserved words (a column named ``order``) survive as identifiers
    only in quoted form; validation matches :func:`sql_identifier`.
    """
    if not name or not all(
        _IDENTIFIER_RE.match(segment) for segment in name.split(".")
    ):
        raise ValueError(f"unsafe SQL identifier: {name!r}")
    return ".".join(f'"{segment}"' for segment in name.split("."))


def sql_path_list(paths: Sequence[str]) -> str:
    """Return ``paths`` as a SQL list literal for ``read_parquet([...])``.

    Built element by element with :func:`sql_literal` so a path cannot break out of
    its own element.
    """
    return "[" + ", ".join(sql_literal(str(path)) for path in paths) + "]"


def _identifier(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def connect(
    profile: RuntimeResourceProfile | None = None,
    *,
    database: str | os.PathLike[str] = ":memory:",
    threads: int | None = None,
    memory_limit: str | None = None,
    temp_directory: str | os.PathLike[str] | None = None,
    preserve_insertion_order: bool = False,
) -> duckdb.DuckDBPyConnection:
    """Create a DuckDB connection with strict resource bounds derived from the system."""
    if profile is None:
        from edgar_sec.foundation.runtime.resources import derive_resources

        profile = derive_resources()

    actual_threads = threads if threads is not None else profile.threads
    actual_memory_limit = (
        memory_limit if memory_limit is not None else profile.memory_limit
    )
    actual_temp_dir = (
        Path(temp_directory).resolve()
        if temp_directory is not None
        else profile.temp_dir
    )
    actual_temp_dir.mkdir(parents=True, exist_ok=True)

    database_path = os.fspath(database)
    if database_path != ":memory:":
        Path(database_path).resolve().parent.mkdir(parents=True, exist_ok=True)
        con = duckdb.connect(
            database=database_path,
            config={"storage_compatibility_version": STORAGE_COMPATIBILITY_VERSION},
        )
    else:
        con = duckdb.connect(database=database_path)
    con.execute("SET threads = ?", [max(1, int(actual_threads))])
    con.execute("SET memory_limit = ?", [str(actual_memory_limit)])
    con.execute("SET temp_directory = ?", [str(actual_temp_dir)])
    con.execute("SET preserve_insertion_order = ?", [bool(preserve_insertion_order)])
    return con


def copy_query_to_parquet(
    con: object,
    query: str,
    destination: os.PathLike[str] | str,
    row_group_size: int | None = None,
    *,
    compression: str = DEFAULT_COMPRESSION,
    params: Sequence[str] | None = None,
    schema: pa.Schema | None = None,
) -> int:
    """Write one query result to Parquet out-of-core and atomically; return the row count.

    Staged beside the destination and renamed, so a failed write leaves no half-written
    shard. With ``schema``, the stage is stream-rewritten under it before the rename.
    """
    effective_row_group_size = resolve_row_group_size(row_group_size)
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    rewritten = path.with_name(f".{path.name}.schema.{os.getpid()}")
    try:
        con.execute(
            f"COPY ({query}) TO {sql_literal(str(tmp))} "
            f"(FORMAT PARQUET, COMPRESSION {compression}, "
            f"ROW_GROUP_SIZE {effective_row_group_size})",
            list(params) if params is not None else None,
        )
        if schema is not None:
            rewrite_parquet_schema(
                tmp,
                rewritten,
                schema,
                compression=compression,
                row_group_size=effective_row_group_size,
            )
            os.replace(rewritten, tmp)
        os.replace(tmp, path)
        _fsync_dir(str(path.parent))
    finally:
        if tmp.exists():
            tmp.unlink()
        if rewritten.exists():
            rewritten.unlink()
    return count_parquet_rows(path)


def _drain_open_result(con: object) -> None:
    """Close an unfinished ``execute()`` result on ``con``, if one is open.

    DuckDB 2.0's relation entry points refuse such a connection;
    ``complete()`` exists only on 2.0, so the guard is a no-op on 1.5.6.
    """
    complete = getattr(con, "complete", None)
    if complete is not None:
        complete()


def _drain_relation(relation: Relation) -> None:
    """Drain the open ``execute()`` result on ``relation``'s connection.

    The connection is reachable as ``_con`` only on 2.0 — the version whose
    materialization checks for an open result — so the guard suffices.
    """
    con = getattr(relation, "_con", None)
    if con is not None:
        _drain_open_result(con)


def relation_table(relation: Relation, *, schema: pa.Schema | None = None) -> pa.Table:
    """Return a relation's Arrow table; with ``schema``, cast to the declared
    schema, absorbing the export's nullability drop on DuckDB 2.0."""
    _drain_relation(relation)
    table = relation.to_arrow_table()
    return cast_table(table, schema) if schema is not None else table


def relation_reader(
    relation: Relation,
    batch_size: int | None = None,
    *,
    schema: pa.Schema | None = None,
) -> pa.RecordBatchReader:
    """Return a relation's streaming Arrow reader; the batch size defaults
    from the runtime settings seam, and ``schema`` casts each batch."""
    _drain_relation(relation)
    reader = relation.to_arrow_reader(batch_size=resolve_read_batch_size(batch_size))
    if schema is None:
        return reader
    return _cast_reader(reader, schema)


def arrow_table(
    con: Connection,
    query: str,
    params: Sequence[object] | Mapping[str, object] | None = None,
    *,
    schema: pa.Schema | None = None,
) -> pa.Table:
    """Return ``query``'s Arrow table through the relation form, the portable
    export on both DuckDB versions (the ``execute()`` form copies and warns on
    2.0); with ``schema``, cast to it, absorbing the export's nullability drop."""
    _drain_open_result(con)
    relation = con.sql(query, params=params) if params is not None else con.sql(query)
    return relation_table(relation, schema=schema)


def arrow_reader(
    con: Connection,
    query: str,
    params: Sequence[object] | Mapping[str, object] | None = None,
    batch_size: int | None = None,
    *,
    schema: pa.Schema | None = None,
) -> pa.RecordBatchReader:
    """Return ``query``'s streaming Arrow reader through the relation form; the
    batch size defaults from the runtime settings seam. The reader holds an open
    result on ``con`` — drain it before executing on ``con`` again (2.0 enforces)."""
    _drain_open_result(con)
    relation = con.sql(query, params=params) if params is not None else con.sql(query)
    return relation_reader(relation, batch_size, schema=schema)


def _cast_reader(
    reader: pa.RecordBatchReader, schema: pa.Schema
) -> pa.RecordBatchReader:
    def batches() -> object:
        for batch in reader:
            yield batch.cast(schema)

    return pa.RecordBatchReader.from_batches(schema, batches())


def find_duplicate_keys(
    con: duckdb.DuckDBPyConnection,
    paths: Sequence[str | os.PathLike[str]],
    key_column: str,
) -> list[str]:
    """Find any duplicate values of ``key_column`` across chunks, up to 100.

    ``key_column`` is required: a dataset's primary key is its own property, not
    something the storage layer asserts on a caller's behalf.
    """
    if not paths:
        return []
    str_paths = [str(Path(p).resolve()) for p in paths]
    literals = ", ".join(sql_literal(p) for p in str_paths)
    col_id = _identifier(key_column)
    query = f"""
        SELECT {col_id}::VARCHAR
        FROM read_parquet([{literals}])
        GROUP BY {col_id}
        HAVING count(*) > 1
        LIMIT 100
    """
    return [row[0] for row in con.execute(query).fetchall()]


def find_null_keys(
    con: duckdb.DuckDBPyConnection,
    paths: Sequence[str | os.PathLike[str]],
    key_column: str,
) -> int:
    """Count null values of ``key_column`` across chunks.

    ``key_column`` is required for the same reason as :func:`find_duplicate_keys`.
    """
    if not paths:
        return 0
    str_paths = [str(Path(p).resolve()) for p in paths]
    literals = ", ".join(sql_literal(p) for p in str_paths)
    col_id = _identifier(key_column)
    query = f"""
        SELECT count(*)
        FROM read_parquet([{literals}])
        WHERE {col_id} IS NULL
    """
    res = con.execute(query).fetchone()
    return int(res[0]) if res else 0


__all__ = [
    "Connection",
    "DuckDBError",
    "InvalidInputError",
    "Relation",
    "STORAGE_COMPATIBILITY_VERSION",
    "arrow_reader",
    "arrow_table",
    "connect",
    "copy_query_to_parquet",
    "find_duplicate_keys",
    "find_null_keys",
    "relation_reader",
    "relation_table",
    "sql_identifier",
    "sql_literal",
    "sql_path_list",
    "sql_quoted_identifier",
]
