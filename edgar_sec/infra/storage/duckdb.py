"""Managed DuckDB connection factory and out-of-core Parquet serialization.

Mandates machine-derived resource limits to prevent out-of-memory errors on large merges.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import duckdb

if TYPE_CHECKING:
    from edgar_sec.foundation.runtime.resources import RuntimeResourceProfile

from .atomic import _fsync_dir
from .parquet import DEFAULT_COMPRESSION, DEFAULT_ROW_GROUP_SIZE


def _quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _identifier(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def connect(
    profile: RuntimeResourceProfile | None = None,
    *,
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

    con = duckdb.connect()
    con.execute("SET threads = ?", [max(1, int(actual_threads))])
    con.execute("SET memory_limit = ?", [str(actual_memory_limit)])
    con.execute("SET temp_directory = ?", [str(actual_temp_dir)])
    con.execute("SET preserve_insertion_order = ?", [bool(preserve_insertion_order)])
    return con


def concat_to_parquet(
    con: duckdb.DuckDBPyConnection,
    input_paths: Sequence[str | os.PathLike[str]],
    output_path: str | os.PathLike[str],
    *,
    order_by: Sequence[str] = ("cik",),
    compression: str = DEFAULT_COMPRESSION,
    row_group_size: int = DEFAULT_ROW_GROUP_SIZE,
) -> int:
    """Concatenate multiple Parquet or JSONL chunks into a single sorted Parquet file."""
    if not input_paths:
        raise ValueError("DuckDB concat requires at least one input file")

    str_paths = [str(Path(p).resolve()) for p in input_paths]
    literals = ", ".join(_quote(p) for p in str_paths)
    source = f"read_parquet([{literals}])"

    order_clauses = ", ".join(_identifier(col) for col in order_by) or _identifier(
        "cik"
    )
    out_str = str(Path(output_path).resolve())
    directory = os.path.dirname(out_str)
    os.makedirs(directory, exist_ok=True)
    tmp_path = f"{out_str}.tmp.{os.getpid()}"

    copy_sql = f"""
        COPY (
            SELECT * FROM {source} ORDER BY {order_clauses}
        ) TO {_quote(tmp_path)}
        (FORMAT PARQUET, COMPRESSION {_quote(compression)}, ROW_GROUP_SIZE {int(row_group_size)})
    """
    try:
        con.execute(copy_sql)
        os.replace(tmp_path, out_str)
        _fsync_dir(directory)
        count_res = con.execute(
            f"SELECT count(*) FROM read_parquet({_quote(out_str)})"
        ).fetchone()
        return int(count_res[0]) if count_res else 0
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def find_duplicate_keys(
    con: duckdb.DuckDBPyConnection,
    paths: Sequence[str | os.PathLike[str]],
    key_column: str = "cik",
) -> list[str]:
    """Find any duplicate primary keys across chunks."""
    if not paths:
        return []
    str_paths = [str(Path(p).resolve()) for p in paths]
    literals = ", ".join(_quote(p) for p in str_paths)
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
    key_column: str = "cik",
) -> int:
    """Count null values for the primary key across chunks."""
    if not paths:
        return 0
    str_paths = [str(Path(p).resolve()) for p in paths]
    literals = ", ".join(_quote(p) for p in str_paths)
    col_id = _identifier(key_column)
    query = f"""
        SELECT count(*)
        FROM read_parquet([{literals}])
        WHERE {col_id} IS NULL
    """
    res = con.execute(query).fetchone()
    return int(res[0]) if res else 0


def find_duplicate_nested_values(
    con: duckdb.DuckDBPyConnection,
    paths: Sequence[str | os.PathLike[str]],
    list_column: str = "filings",
    field_name: str = "accession_number",
) -> list[str]:
    """Find duplicate values inside a nested struct array (e.g. unnesting filings.accession_number)."""
    if not paths:
        return []
    str_paths = [str(Path(p).resolve()) for p in paths]
    literals = ", ".join(_quote(p) for p in str_paths)
    col_id = _identifier(list_column)
    field_id = _identifier(field_name)
    query = f"""
        SELECT val::VARCHAR
        FROM (
            SELECT unnest({col_id}).{field_id} AS val
            FROM read_parquet([{literals}])
        )
        WHERE val IS NOT NULL
        GROUP BY val
        HAVING count(*) > 1
        LIMIT 100
    """
    return [row[0] for row in con.execute(query).fetchall()]


__all__ = [
    "concat_to_parquet",
    "connect",
    "find_duplicate_keys",
    "find_duplicate_nested_values",
    "find_null_keys",
]
