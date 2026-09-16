"""DuckDB-backed reads for viewer datasets.

All viewer reads go through DuckDB table functions (``read_parquet`` /
``read_json_auto``) with server-bound paths; the browser never supplies SQL
paths or identifiers that are not validated here. Results are serialized
without pandas via :mod:`defs.viewer.serialize`.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

import duckdb

from .serialize import json_safe
from .sql_guard import SqlGuardError, validate_read_only

MAX_SQL_ROWS = 10_000
MAX_PAYLOAD_BYTES = 8 * 1024 * 1024
DEFAULT_TIMEOUT_S = 15.0

_ROWS_CTE = "__viewer_page"


class DatasetError(ValueError):
    """Raised when an artifact cannot be read as a dataset."""


@dataclass(frozen=True)
class DatasetRef:
    """A resolved artifact path plus its tabular format."""

    dataset_id: str
    path: Path | None
    fmt: str
    paths: tuple[Path, ...] = ()
    table: str | None = None

    def __post_init__(self) -> None:
        if self.path is None and not self.paths:
            raise ValueError("dataset must have at least one path")
        if self.path is not None and not self.paths:
            object.__setattr__(self, "paths", (self.path,))
        elif self.path is None:
            object.__setattr__(self, "path", self.paths[0])

    @property
    def reader_expression(self) -> str:
        if self.fmt == "parquet":
            if len(self.paths) > 1:
                paths = ", ".join(
                    f"'{str(path).replace(chr(39), chr(39) * 2)}'"
                    for path in self.paths
                )
                return f"read_parquet([{paths}], union_by_name=true)"
            return f"read_parquet('{self._sql_path()}')"
        if self.fmt == "jsonl":
            if len(self.paths) > 1:
                paths = ", ".join(
                    f"'{str(path).replace(chr(39), chr(39) * 2)}'"
                    for path in self.paths
                )
                return (
                    f"read_json_auto([{paths}], format='newline_delimited', "
                    "union_by_name=true)"
                )
            return f"read_json_auto('{self._sql_path()}', format='newline_delimited')"
        if self.fmt == "sqlite":
            path_str = self._sql_path()
            table_name = self.table
            if not table_name:
                from defs.viewer.discover import _get_sqlite_tables

                tables = _get_sqlite_tables(self.path)
                if "normalized_documents" in tables:
                    table_name = "normalized_documents"
                elif "filing_documents" in tables:
                    table_name = "filing_documents"
                elif "document_blobs" in tables:
                    table_name = "document_blobs"
                elif tables:
                    table_name = tables[0]
                else:
                    table_name = "sqlite_master"
            table_esc = table_name.replace("'", "''")
            return f"sqlite_scan('{path_str}', '{table_esc}')"
        raise DatasetError(f"unsupported dataset format: {self.fmt}")

    def _sql_path(self) -> str:
        return str(self.paths[0]).replace("'", "''")


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _connect(_ref: DatasetRef | None = None) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(database=":memory:")


def _execute_with_timeout(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    params: list,
    timeout_s: float = DEFAULT_TIMEOUT_S,
):
    timer = threading.Timer(timeout_s, conn.interrupt)
    timer.daemon = True
    timer.start()
    try:
        return conn.execute(sql, params)
    finally:
        timer.cancel()


def dataset_schema(ref: DatasetRef) -> list[dict]:
    """Column names, types, null counts, and approx distinct counts."""
    conn = _connect(ref)
    try:
        described = _execute_with_timeout(
            conn, f"DESCRIBE SELECT * FROM {ref.reader_expression}", []
        ).fetchall()
        names = [row[0] for row in described]
        types = [row[1] for row in described]
        if not names:
            return []
        aggregates = ", ".join(
            [
                f"COUNT({_quote_ident(name)}) AS {(_quote_ident('non_null_' + name))}, "
                f"APPROX_COUNT_DISTINCT({_quote_ident(name)}) AS "
                f"{_quote_ident('distinct_' + name)}"
                for name in names
            ]
        )
        totals = _execute_with_timeout(
            conn,
            f"SELECT COUNT(*) AS rows_total, {aggregates} FROM {ref.reader_expression}",
            [],
        ).fetchone()
        rows_total = int(totals[0])
        columns = []
        for index, name in enumerate(names):
            non_null = int(totals[1 + index * 2])
            approx_distinct = int(totals[2 + index * 2])
            columns.append(
                {
                    "name": name,
                    "duckdb_type": types[index],
                    "null_count": rows_total - non_null,
                    "approx_distinct": approx_distinct,
                }
            )
        return columns
    except duckdb.Error as exc:
        name = ref.path.name if ref.path else ref.dataset_id
        raise DatasetError(f"cannot read dataset {name}: {exc}") from exc
    finally:
        conn.close()


def dataset_rows(
    ref: DatasetRef,
    *,
    offset: int = 0,
    limit: int = 200,
    sort: str | None = None,
    direction: str = "asc",
    filters: list[dict] | None = None,
    search: str | None = None,
    search_columns: list[str] | None = None,
    include_total: bool | None = None,
) -> dict:
    """One bounded page of rows plus cursor information (no unbounded scans)."""
    if limit < 1 or limit > 1000:
        raise ValueError("limit must be between 1 and 1000")
    if offset < 0:
        raise ValueError("offset must be >= 0")
    if direction not in {"asc", "desc"}:
        raise ValueError("direction must be 'asc' or 'desc'")

    columns = dataset_schema(ref)
    names = [column["name"] for column in columns]
    if sort is not None and sort not in names:
        raise ValueError(f"unknown sort column: {sort!r}")

    params: list = []
    where_clause = ""
    if search:
        targets = search_columns or names
        unknown = [column for column in targets if column not in names]
        if unknown:
            raise ValueError(f"unknown search columns: {unknown}")
        search_clauses = []
        for name in targets:
            search_clauses.append(f"CAST({_quote_ident(name)} AS VARCHAR) ILIKE ?")
            params.append(f"%{search}%")
        where_clause = " WHERE " + " OR ".join(search_clauses)
    if filters:
        clauses = []
        type_by_name = {
            column["name"]: column["duckdb_type"].upper() for column in columns
        }
        order_ops = {"gt", "ge", "lt", "le"}
        for item in filters:
            if not isinstance(item, dict) or not isinstance(item.get("column"), str):
                raise ValueError("each filter must contain a column, op, and value")
            name, op = item["column"], item.get("op")
            if name not in type_by_name:
                raise ValueError(f"unknown filter column: {name!r}")
            if not isinstance(op, str):
                raise ValueError("filter op must be a string")
            duckdb_type = type_by_name[name]
            is_orderable = "INT" in duckdb_type or duckdb_type.startswith(
                ("DECIMAL", "DOUBLE", "FLOAT", "REAL", "NUMERIC", "DATE", "TIME")
            )
            if op in order_ops and not is_orderable:
                raise ValueError(f"operator {op!r} is invalid for column {name!r}")
            if op not in order_ops | {
                "contains",
                "not_contains",
                "eq",
                "ne",
                "empty",
                "not_empty",
            }:
                raise ValueError(f"unknown filter operator: {op!r}")
            ident = _quote_ident(name)
            if op == "empty":
                clauses.append(f"({ident} IS NULL OR CAST({ident} AS VARCHAR) = '')")
            elif op == "not_empty":
                clauses.append(
                    f"({ident} IS NOT NULL AND CAST({ident} AS VARCHAR) <> '')"
                )
            elif op in {"contains", "not_contains"}:
                clauses.append(
                    f"CAST({ident} AS VARCHAR) {'NOT ' if op == 'not_contains' else ''}ILIKE ?"
                )
                params.append(f"%{item.get('value', '')}%")
            else:
                sql_op = {
                    "ge": ">=",
                    "le": "<=",
                    "ne": "<>",
                    "eq": "=",
                    "gt": ">",
                    "lt": "<",
                }.get(op, op)
                clauses.append(f"{ident} {sql_op} ?")
                params.append(item.get("value"))
        if clauses:
            conj = " AND " + " AND ".join(clauses)
            where_clause = (
                where_clause + conj
                if where_clause
                else " WHERE " + " AND ".join(clauses)
            )

    order_clause = ""
    if sort is not None:
        order_clause = f" ORDER BY {_quote_ident(sort)} {direction.upper()}"

    conn = _connect(ref)
    try:
        base = f"SELECT * FROM {ref.reader_expression}"
        filtered = f"{base}{where_clause}"
        # has_more comes from fetching limit+1 rows; never from a count query.
        page_sql = (
            f"SELECT * FROM ({filtered}{order_clause}) {_ROWS_CTE} LIMIT ? OFFSET ?"
        )
        result = _execute_with_timeout(conn, page_sql, [*params, limit + 1, offset])
        arrow = result.arrow().read_all()
        items = []
        for record in arrow.to_pylist():
            processed_record = {}
            for k, v in record.items():
                if isinstance(v, bytes):
                    is_comp = v.startswith(b"\x28\xb5\x2f\xfd")
                    if len(v) > 128 or is_comp:
                        processed_record[k] = {
                            "__blob__": True,
                            "size_bytes": len(v),
                            "is_compressed": is_comp,
                        }
                    else:
                        processed_record[k] = json_safe(v)
                else:
                    processed_record[k] = json_safe(v)
            items.append(processed_record)
        has_more = len(items) > limit
        items = items[:limit]

        total_rows = None
        if include_total is None:
            include_total = ref.fmt == "parquet" and not filters
        if include_total:
            count_sql = f"SELECT COUNT(*) FROM ({filtered}) {_ROWS_CTE}"
            total_rows = int(
                _execute_with_timeout(conn, count_sql, params).fetchone()[0]
            )

        return {
            "items": items,
            "has_more": has_more,
            "next_cursor": offset + limit if has_more else None,
            "total_rows": total_rows,
            "truncated": False,
        }
    except duckdb.Error as exc:
        raise DatasetError(f"query failed: {exc}") from exc
    finally:
        conn.close()


def dataset_column_stats(ref: DatasetRef, top_k: int = 5) -> list[dict]:
    """Per-column stats including top values for low-cardinality strings."""
    columns = dataset_schema(ref)
    conn = _connect(ref)
    try:
        for column in columns:
            column["top_values"] = []
            name = column["name"]
            is_string = column["duckdb_type"].upper().startswith("VARCHAR")
            if is_string and 0 < column["approx_distinct"] <= 20:
                values = _execute_with_timeout(
                    conn,
                    f"SELECT {_quote_ident(name)} AS value, COUNT(*) AS count "
                    f"FROM {ref.reader_expression} "
                    f"WHERE {_quote_ident(name)} IS NOT NULL "
                    f"GROUP BY 1 ORDER BY count DESC, value LIMIT ?",
                    [top_k],
                ).fetchall()
                column["top_values"] = [
                    {"value": json_safe(value), "count": count}
                    for value, count in values
                ]
        return columns
    except duckdb.Error as exc:
        raise DatasetError(f"stats failed: {exc}") from exc
    finally:
        conn.close()


def run_dataset_sql(
    ref: DatasetRef, query: str, *, timeout_s: float = DEFAULT_TIMEOUT_S
) -> dict:
    """Run one guarded, read-only query against a single dataset."""
    try:
        validated = validate_read_only(query)
    except SqlGuardError as exc:
        raise DatasetError(str(exc)) from exc
    lowered = validated.lower()
    if "read_parquet(" in lowered or "read_json" in lowered or "read_csv" in lowered:
        raise DatasetError("table functions are not allowed in console queries")
    wrapped = f"SELECT * FROM (\n{validated}\n) __viewer_console LIMIT {MAX_SQL_ROWS}"
    conn = _connect(ref)
    started = time.monotonic()
    try:
        # Expose the selected artifact as the only relation the console can
        # query: a private view on this request's in-memory connection.
        conn.execute(f"CREATE VIEW dataset AS SELECT * FROM {ref.reader_expression}")
        result = _execute_with_timeout(conn, wrapped, [], timeout_s=timeout_s)
        columns = [description[0] for description in result.description]
        rows: list[dict] = []
        truncated = False
        while True:
            batch = result.fetchmany(500)
            if not batch:
                break
            for row in batch:
                rows.append(json_safe(dict(zip(columns, row))))
                if len(rows) >= MAX_SQL_ROWS:
                    truncated = True
                    break
            payload_estimate = sum(len(str(row)) for row in rows[-500:])
            if payload_estimate > MAX_PAYLOAD_BYTES:
                truncated = True
            if truncated:
                break
        return {
            "columns": columns,
            "rows": rows,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
            "truncated": truncated,
        }
    except duckdb.Error as exc:
        message = str(exc)
        if "INTERRUPT" in message.upper() or "interrupt" in message:
            raise DatasetError(
                f"query exceeded {timeout_s:g}s and was interrupted"
            ) from exc
        raise DatasetError(message) from exc
    finally:
        conn.close()


def dataset_blob(
    ref: DatasetRef,
    *,
    column: str,
    pk_col: str | None = None,
    pk_val: str | None = None,
    row_index: int | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict:
    """Fetch and lazily decompress one BLOB field from a dataset."""
    conn = _connect(ref)
    try:
        col_ident = _quote_ident(column)
        if pk_col and pk_val is not None:
            pk_ident = _quote_ident(pk_col)
            sql = f"SELECT {col_ident} FROM {ref.reader_expression} WHERE {pk_ident} = ? LIMIT 1"
            res = _execute_with_timeout(
                conn, sql, [pk_val], timeout_s=timeout_s
            ).fetchone()
        elif row_index is not None:
            sql = f"SELECT {col_ident} FROM {ref.reader_expression} LIMIT 1 OFFSET ?"
            res = _execute_with_timeout(
                conn, sql, [row_index], timeout_s=timeout_s
            ).fetchone()
        else:
            raise ValueError("either (pk_col, pk_val) or row_index must be provided")

        if not res or res[0] is None:
            raise DatasetError(f"blob not found for column {column!r}")

        raw_blob = bytes(res[0])
        is_compressed = raw_blob.startswith(b"\x28\xb5\x2f\xfd")
        if is_compressed:
            try:
                import importlib

                schemas = importlib.import_module(
                    "phases.025_webpage_storage.core.schemas"
                )
                decompressed = schemas.decompress_payload(raw_blob)
            except (ImportError, AttributeError, ValueError):
                import zstandard

                decompressed = zstandard.ZstdDecompressor().decompress(raw_blob)
        else:
            decompressed = raw_blob

        comp_bytes = len(raw_blob)
        decomp_bytes = len(decompressed)
        ratio = round(decomp_bytes / comp_bytes, 2) if comp_bytes > 0 else 1.0

        try:
            text = decompressed.decode("utf-8")
            stripped = text.strip()
            if stripped.startswith(("<html", "<!DOCTYPE", "<HTML", "<!doctype")):
                mime = "text/html"
            elif stripped.startswith(("#", "```", "|")):
                mime = "text/markdown"
            elif stripped.startswith(("{", "[")):
                mime = "application/json"
            else:
                mime = "text/plain"
        except UnicodeDecodeError:
            text = None
            mime = "application/octet-stream"

        return {
            "column": column,
            "is_compressed": is_compressed,
            "compressed_bytes": comp_bytes,
            "decompressed_bytes": decomp_bytes,
            "compression_ratio": ratio,
            "mime_type": mime,
            "text": text,
            "preview": text[:500] if text else None,
        }
    except duckdb.Error as exc:
        raise DatasetError(f"blob query failed: {exc}") from exc
    finally:
        conn.close()
