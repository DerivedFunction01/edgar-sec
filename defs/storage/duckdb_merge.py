"""DuckDB operations for validating and serializing file-backed datasets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import duckdb
import pyarrow as pa

from .errors import StorageError


@dataclass(frozen=True)
class MergeValidationSpec:
    schema: pa.Schema
    key_field: str
    schema_version: str
    fingerprint: str
    terminal_statuses: tuple[str, ...]
    schema_version_field: str = "schema_version"
    fingerprint_field: str = "input_fingerprint"
    status_field: str = "status"
    uniqueness_paths: tuple[tuple[str, str], ...] = ()
    order_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class MergeValidation:
    row_count: int
    distinct_keys: int
    invalid_field_rows: int
    duplicate_keys: tuple[str, ...]
    uniqueness_duplicate_counts: dict[tuple[str, str], int]


def connect(
    *,
    threads: int | None = None,
    memory_limit: str | None = None,
    temp_directory: str | None = None,
    preserve_insertion_order: bool = True,
):
    con = duckdb.connect()
    if threads is not None:
        con.execute("SET threads = ?", [max(1, int(threads))])
    if memory_limit is not None:
        con.execute("SET memory_limit = ?", [memory_limit])
    if temp_directory is not None:
        con.execute("SET temp_directory = ?", [str(Path(temp_directory).resolve())])
    con.execute("SET preserve_insertion_order = ?", [bool(preserve_insertion_order)])
    return con


def _quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _duck_type(arrow_type: pa.DataType) -> str:
    if pa.types.is_string(arrow_type):
        return "VARCHAR"
    if pa.types.is_boolean(arrow_type):
        return "BOOLEAN"
    if pa.types.is_int32(arrow_type):
        return "INTEGER"
    if pa.types.is_int64(arrow_type):
        return "BIGINT"
    if pa.types.is_float64(arrow_type):
        return "DOUBLE"
    if pa.types.is_date32(arrow_type):
        return "DATE"
    if pa.types.is_timestamp(arrow_type):
        return "TIMESTAMP"
    if pa.types.is_decimal(arrow_type):
        return f"DECIMAL({arrow_type.precision},{arrow_type.scale})"
    if pa.types.is_list(arrow_type):
        return f"{_duck_type(arrow_type.value_type)}[]"
    if pa.types.is_struct(arrow_type):
        fields = ", ".join(
            f"{_identifier(field.name)} {_duck_type(field.type)}"
            for field in arrow_type
        )
        return f"STRUCT({fields})"
    raise StorageError(f"unsupported Arrow type for DuckDB scan: {arrow_type}")


def jsonl_columns(schema: pa.Schema) -> dict[str, str]:
    return {field.name: _duck_type(field.type) for field in schema}


def _reader(format_name: str, paths: list[str], schema: pa.Schema) -> str:
    if not paths:
        raise StorageError("DuckDB merge requires at least one input file")
    literals = ", ".join(_quote(path) for path in paths)
    if format_name == "parquet":
        return f"read_parquet([{literals}])"
    if format_name == "jsonl":
        columns = ", ".join(
            f"{_quote(name)}: {_quote(dtype)}"
            for name, dtype in jsonl_columns(schema).items()
        )
        return f"read_ndjson([{literals}], columns={{{columns}}})"
    raise StorageError(f"unsupported storage format: {format_name}")


def duplicate_values(
    con,
    format_name: str,
    paths: list[str],
    schema: pa.Schema,
    path: tuple[str, str],
) -> list[str]:
    source = _reader(format_name, paths, schema)
    column, nested_field = (_identifier(part) for part in path)
    query = f"""
        SELECT value::VARCHAR
        FROM (
            SELECT unnest({column}).{nested_field} AS value
            FROM {source}
        )
        WHERE value IS NOT NULL
        GROUP BY value
        HAVING count(*) > 1
        ORDER BY value
        LIMIT 100
    """
    return [row[0] for row in con.execute(query).fetchall()]


def validate_files(
    con,
    format_name: str,
    paths: list[str],
    spec: MergeValidationSpec,
) -> MergeValidation:
    source = _reader(format_name, paths, spec.schema)
    key = _identifier(spec.key_field)
    schema_version = _identifier(spec.schema_version_field)
    fingerprint = _identifier(spec.fingerprint_field)
    status = _identifier(spec.status_field)
    terminal = ", ".join(_quote(value) for value in spec.terminal_statuses)
    row_count, distinct_keys, invalid = con.execute(
        f"""
        SELECT count(*), count(DISTINCT {key}),
               count(*) FILTER (
                   WHERE {schema_version} != ?
                      OR {fingerprint} != ?
                      OR {status} NOT IN ({terminal})
               )
        FROM {source}
        """,
        [spec.schema_version, spec.fingerprint],
    ).fetchone()
    duplicate_rows = con.execute(
        f"""
        SELECT {key}::VARCHAR
        FROM {source}
        GROUP BY {key}
        HAVING count(*) > 1
        ORDER BY {key}
        LIMIT 100
        """
    ).fetchall()
    uniqueness_counts = {}
    for path in spec.uniqueness_paths:
        column, nested_field = (_identifier(part) for part in path)
        duplicate_count = con.execute(
            f"""
            SELECT count(*) FROM (
                SELECT unnest({column}).{nested_field} AS value
                FROM {source}
            )
            WHERE value IS NOT NULL
            GROUP BY value
            HAVING count(*) > 1
            """
        ).fetchall()
        uniqueness_counts[path] = len(duplicate_count)
    return MergeValidation(
        row_count=int(row_count),
        distinct_keys=int(distinct_keys),
        invalid_field_rows=int(invalid),
        duplicate_keys=tuple(row[0] for row in duplicate_rows),
        uniqueness_duplicate_counts=uniqueness_counts,
    )


def ordered_keys(
    con, format_name: str, paths: str | list[str], spec: MergeValidationSpec
) -> list[str]:
    source = _reader(
        format_name, [paths] if isinstance(paths, str) else paths, spec.schema
    )
    order = ", ".join(_identifier(name) for name in spec.order_by) or _identifier(
        spec.key_field
    )
    return [
        row[0]
        for row in con.execute(
            f"SELECT {_identifier(spec.key_field)}::VARCHAR FROM {source} ORDER BY {order}"
        ).fetchall()
    ]


def count_rows(con, path: str) -> int:
    suffix = Path(path).suffix.lower()
    if suffix == ".parquet":
        return int(
            con.execute(
                f"SELECT count(*) FROM read_parquet({_quote(path)})"
            ).fetchone()[0]
        )
    if suffix == ".jsonl":
        return int(
            con.execute(f"SELECT count(*) FROM read_ndjson({_quote(path)})").fetchone()[
                0
            ]
        )
    raise StorageError(f"unsupported finalized artifact suffix: {suffix}")


def count_nested_values(
    con,
    format_name: str,
    paths: list[str],
    schema: pa.Schema,
    path: tuple[str, str],
) -> int:
    source = _reader(format_name, paths, schema)
    column, nested_field = (_identifier(part) for part in path)
    return int(
        con.execute(
            f"""SELECT count(*) FROM (
                    SELECT unnest({column}).{nested_field} AS value
                    FROM {source}
                ) WHERE value IS NOT NULL"""
        ).fetchone()[0]
    )


def concat_to_parquet(
    con,
    format_name: str,
    paths: list[str],
    spec: MergeValidationSpec,
    output_path: str,
    *,
    compression: str = "zstd",
    row_group_size: int = 128000,
) -> None:
    source = _reader(format_name, paths, spec.schema)
    order = ", ".join(_identifier(name) for name in spec.order_by) or _identifier(
        spec.key_field
    )
    output = _quote(output_path)
    parent = Path(output_path).parent
    if str(parent):
        parent.mkdir(parents=True, exist_ok=True)
    try:
        con.execute(
            f"""COPY (
                    SELECT * FROM {source} ORDER BY {order}
                ) TO {output}
                (FORMAT PARQUET, COMPRESSION {_quote(compression)},
                 ROW_GROUP_SIZE {int(row_group_size)})"""
        )
    except duckdb.Error as exc:
        raise StorageError(f"DuckDB failed to serialize {output_path}: {exc}") from exc


__all__ = [
    "MergeValidation",
    "MergeValidationSpec",
    "concat_to_parquet",
    "connect",
    "count_nested_values",
    "count_rows",
    "duplicate_values",
    "jsonl_columns",
    "ordered_keys",
    "validate_files",
]
