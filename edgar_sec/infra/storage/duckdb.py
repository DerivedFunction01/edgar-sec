"""Managed DuckDB connection factory and out-of-core Parquet serialization.

Mandates machine-derived resource limits to prevent out-of-memory errors on large merges.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb

if TYPE_CHECKING:
    from edgar_sec.foundation.runtime.resources import RuntimeResourceProfile

from .atomic import _fsync_dir
from .parquet import (
    DEFAULT_COMPRESSION,
    count_parquet_rows,
)
from edgar_sec.foundation.runtime.settings.parquet import resolve_row_group_size

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
) -> int:
    """Write one query result to Parquet out-of-core and atomically; return the row count.

    Staged beside the destination and renamed, so a failed write leaves no half-written
    shard. ``params`` binds source paths, keeping the caller's ``query`` a constant.
    """
    effective_row_group_size = resolve_row_group_size(row_group_size)
    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        con.execute(
            f"COPY ({query}) TO {sql_literal(str(tmp))} "
            f"(FORMAT PARQUET, COMPRESSION {compression}, "
            f"ROW_GROUP_SIZE {effective_row_group_size})",
            list(params) if params is not None else None,
        )
        os.replace(tmp, path)
        _fsync_dir(str(path.parent))
    finally:
        if tmp.exists():
            tmp.unlink()
    return count_parquet_rows(path)


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
    "connect",
    "copy_query_to_parquet",
    "find_duplicate_keys",
    "find_null_keys",
    "sql_identifier",
    "sql_literal",
    "sql_path_list",
]
