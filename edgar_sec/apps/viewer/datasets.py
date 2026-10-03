"""Bounded, read-only DuckDB access to one browsed dataset.

A sort column, filter operator, and search term all arrive from a browser: each is
either matched against the reported schema or bound as a parameter. Sources are never
opened writable — DuckDB attaches ``READ_ONLY``, SQLite goes through ``sqlite_scan``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from edgar_sec.apps.viewer.model import DatasetError
from edgar_sec.apps.viewer.session import (
    DEFAULT_QUERY_TIMEOUT_S,
)
from edgar_sec.apps.viewer.session import (
    execute_bounded as _execute,
)
from edgar_sec.apps.viewer.session import (
    open_connection as _open,
)
from edgar_sec.foundation.serialization import json_safe

__all__ = [
    "MAX_BLOB_PREVIEW",
    "MAX_LIMIT",
    "MAX_PAGE_BYTES",
    "DatasetError",
    "DatasetRef",
    "dataset_blob",
    "dataset_column_stats",
    "dataset_rows",
    "dataset_schema",
]

MAX_LIMIT = 1000
MIN_LIMIT = 1
DEFAULT_LIMIT = 200
MAX_PAGE_BYTES = 4 * 1024 * 1024
MAX_SEARCH_COLUMNS = 64

# DuckDB's zstd frame magic. A payload that starts with it is compressed; the
# viewer never guesses otherwise, because a coincidental match would corrupt the
# output rather than merely mislabel it.
_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
_INLINE_BLOB_LIMIT = 128
MAX_BLOB_PREVIEW = 500

_ROWS_CTE = "__viewer_page"

_ORDER_OPS = frozenset({"gt", "ge", "lt", "le"})
_TEXT_OPS = frozenset({"contains", "not_contains"})
_COMPARISON_OPS = frozenset({"eq", "ne", "gt", "ge", "lt", "le"})
_NULL_OPS = frozenset({"empty", "not_empty"})
_ALL_OPS = _ORDER_OPS | _TEXT_OPS | _COMPARISON_OPS | _NULL_OPS

# DuckDB types where a range comparison is meaningful; on VARCHAR it is lexicographic,
# so a range operator there is refused rather than silently answering another question.
_ORDERABLE_TYPE_PREFIXES = (
    "DECIMAL",
    "DOUBLE",
    "FLOAT",
    "REAL",
    "NUMERIC",
    "DATE",
    "TIME",
    "TIMESTAMP",
    "INTERVAL",
)


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _quote_path(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


@dataclass(frozen=True)
class DatasetRef:
    """One browsed dataset: its resolved part list and how to read it.

    ``paths`` is the whole definition of the relation — DuckDB reads the list directly,
    so a 37-part snapshot costs no copy step.
    """

    dataset_id: str
    paths: tuple[Path, ...]
    fmt: str = "parquet"
    table: str | None = None

    def __post_init__(self) -> None:
        if not self.paths:
            raise DatasetError("dataset must have at least one part")
        if any(not path.is_file() for path in self.paths):
            missing = next(path for path in self.paths if not path.is_file())
            raise DatasetError(f"dataset part is absent: {missing}")

    @property
    def first(self) -> Path:
        return self.paths[0]

    @property
    def reader_expression(self) -> str:
        """A DuckDB relation over every part, with server-bound paths only."""
        if self.fmt == "parquet":
            listed = ", ".join(_quote_path(path) for path in self.paths)
            if len(self.paths) == 1:
                return f"read_parquet({listed})"
            return f"read_parquet([{listed}], union_by_name=true)"
        if self.fmt == "csv":
            if self.first.suffix.lower() == ".tsv":
                return f"read_csv_auto({_quote_path(self.first)}, delim='\\t')"
            return f"read_csv_auto({_quote_path(self.first)})"
        if self.fmt == "jsonl":
            return (
                f"read_json_auto({_quote_path(self.first)}, format='newline_delimited')"
            )
        if self.fmt == "sqlite":
            if not self.table:
                raise DatasetError("a SQLite dataset must name a table")
            return f"sqlite_scan({_quote_path(self.first)}, {_quote_path(Path(self.table))})"
        if self.fmt == "duckdb":
            if not self.table:
                raise DatasetError("a DuckDB dataset must name a table")
            schema, separator, table = self.table.partition("::")
            if not separator:
                schema, table = "main", schema
            return f'"viewer_database".{_quote_ident(schema)}.{_quote_ident(table)}'
        raise DatasetError(f"unsupported dataset format: {self.fmt}")

    def prepare_connection(self, conn) -> None:
        """Attach native DuckDB sources read-only before using their relation."""
        if self.fmt == "duckdb":
            conn.execute(
                f"ATTACH {_quote_path(self.first)} AS viewer_database (READ_ONLY)"
            )


def _open_ref(ref: DatasetRef):
    conn = _open()
    try:
        ref.prepare_connection(conn)
    except Exception as exc:
        conn.close()
        raise _error(ref, exc) from exc
    return conn


def _error(ref: DatasetRef, exc: Exception) -> DatasetError:
    if "INTERRUPT" in str(exc).upper():
        return DatasetError("query exceeded its time budget and was interrupted")
    return DatasetError(f"cannot read {ref.first.name}: {exc}")


def dataset_schema(
    ref: DatasetRef, timeout_s: float = DEFAULT_QUERY_TIMEOUT_S
) -> list[dict]:
    """Return column names and types without scanning the full relation."""
    conn = _open_ref(ref)
    try:
        described = _execute(
            conn, f"DESCRIBE SELECT * FROM {ref.reader_expression}", [], timeout_s
        ).fetchall()
        names = [str(row[0]) for row in described]
        types = [str(row[1]) for row in described]
        return [
            {
                "name": name,
                "duckdb_type": types[index],
                "null_count": None,
                "approx_distinct": None,
            }
            for index, name in enumerate(names)
        ]
    except Exception as exc:
        raise _error(ref, exc) from exc
    finally:
        conn.close()


def dataset_rows(
    ref: DatasetRef,
    *,
    offset: int = 0,
    limit: int = DEFAULT_LIMIT,
    sort: str | None = None,
    direction: str = "asc",
    filters: list[dict] | None = None,
    search: str | None = None,
    search_columns: list[str] | None = None,
    include_total: bool | None = None,
    timeout_s: float = DEFAULT_QUERY_TIMEOUT_S,
) -> dict:
    """One bounded page of rows, with cursor information.

    ``has_more`` comes from fetching ``limit + 1``, never a COUNT, so paging costs no
    more than the page. ``total_rows`` is off by default for a filtered page.
    """
    if not MIN_LIMIT <= limit <= MAX_LIMIT:
        raise DatasetError(f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}")
    if offset < 0:
        raise DatasetError("offset must be >= 0")
    if direction not in {"asc", "desc"}:
        raise DatasetError("direction must be 'asc' or 'desc'")

    columns = dataset_schema(ref, timeout_s)
    by_name = {column["name"]: column for column in columns}

    if sort is not None and sort not in by_name:
        raise DatasetError(f"unknown sort column: {sort!r}")

    params: list = []
    search_clauses: list[str] = []
    filter_clauses: list[str] = []

    if search:
        targets = search_columns or list(by_name)
        if len(targets) > MAX_SEARCH_COLUMNS:
            raise DatasetError("too many search columns")
        unknown = [name for name in targets if name not in by_name]
        if unknown:
            raise DatasetError(f"unknown search columns: {unknown}")
        # CAST: ILIKE on a non-VARCHAR column is a type error in DuckDB.
        pattern = f"%{search}%"
        for name in targets:
            search_clauses.append(f"CAST({_quote_ident(name)} AS VARCHAR) ILIKE ?")
            params.append(pattern)

    for item in filters or []:
        filter_clauses.append(_filter_clause(item, by_name, params))

    # Search is one OR-group, filters one AND-group; the two are AND-ed together.
    groups: list[str] = []
    if search_clauses:
        groups.append(" OR ".join(search_clauses))
    if filter_clauses:
        groups.append(" AND ".join(filter_clauses))
    where_clause = f" WHERE {' AND '.join(groups)}" if groups else ""
    order_clause = f" ORDER BY {_quote_ident(sort)} {direction.upper()}" if sort else ""

    conn = _open_ref(ref)
    try:
        page_sql = (
            f"SELECT * FROM (SELECT * FROM {ref.reader_expression}{where_clause}"
            f"{order_clause}) {_ROWS_CTE} LIMIT ? OFFSET ?"
        )
        result = _execute(conn, page_sql, [*params, limit + 1, offset], timeout_s)
        column_names = [column[0] for column in result.description]
        items: list[dict] = []
        payload_bytes = 0
        has_more = False
        while len(items) < limit + 1:
            record = result.fetchone()
            if record is None:
                break
            rendered = _render_row(dict(zip(column_names, record, strict=True)))
            row_bytes = len(
                json.dumps(rendered, separators=(",", ":"), ensure_ascii=False).encode(
                    "utf-8"
                )
            )
            if len(items) >= limit or payload_bytes + row_bytes > MAX_PAGE_BYTES:
                has_more = True
                if not items:
                    raise DatasetError(
                        "a single row exceeds the viewer's response-size limit"
                    )
                break
            items.append(rendered)
            payload_bytes += row_bytes

        if include_total is None:
            include_total = False
        total_rows = None
        if include_total:
            total_rows = int(
                _execute(
                    conn,
                    f"SELECT COUNT(*) FROM (SELECT * FROM {ref.reader_expression}"
                    f"{where_clause}) {_ROWS_CTE}",
                    params,
                    timeout_s,
                ).fetchone()[0]
            )

        return {
            "items": items,
            "has_more": has_more,
            "next_cursor": offset + len(items) if has_more else None,
            "total_rows": total_rows,
            "truncated": False,
        }
    except DatasetError:
        raise
    except Exception as exc:
        raise _error(ref, exc) from exc
    finally:
        conn.close()


def _filter_clause(item: dict, by_name: dict, params: list) -> str:
    """Build one ``AND``-composed filter clause.

    Every failure here is a request the dataset cannot answer, refused by name: unknown
    column, unknown operator, or a range operator where a range is meaningless.
    """
    if not isinstance(item, dict):
        raise DatasetError("each filter must be an object")
    name = item.get("column")
    op = item.get("op")
    if not isinstance(name, str) or name not in by_name:
        raise DatasetError(f"unknown filter column: {name!r}")
    if not isinstance(op, str) or op not in _ALL_OPS:
        raise DatasetError(f"unknown filter operator: {op!r}")

    duckdb_type = by_name[name]["duckdb_type"].upper()
    orderable = "INT" in duckdb_type or duckdb_type.startswith(_ORDERABLE_TYPE_PREFIXES)
    if op in _ORDER_OPS and not orderable:
        raise DatasetError(f"operator {op!r} is invalid for column {name!r}")

    ident = _quote_ident(name)
    if op == "empty":
        return f"({ident} IS NULL OR CAST({ident} AS VARCHAR) = '')"
    if op == "not_empty":
        return f"({ident} IS NOT NULL AND CAST({ident} AS VARCHAR) <> '')"
    if op in _TEXT_OPS:
        keyword = "NOT " if op == "not_contains" else ""
        clauses = [f"CAST({ident} AS VARCHAR) {keyword}ILIKE ?"]
        params.append(f"%{item.get('value', '')}%")
        return " OR ".join(clauses)
    sql_op = {
        "eq": "=",
        "ne": "<>",
        "gt": ">",
        "ge": ">=",
        "lt": "<",
        "le": "<=",
    }[op]
    params.append(item.get("value"))
    return f"{ident} {sql_op} ?"


def _render_row(record: dict) -> dict:
    """Convert one Arrow row to a JSON-safe mapping.

    A large ``bytes`` value becomes a marker rather than megabytes of base64 per cell;
    short values are inlined, since a marker would be longer than the value.
    """
    rendered: dict = {}
    for key, value in record.items():
        if isinstance(value, bytes) and (
            len(value) > _INLINE_BLOB_LIMIT or value.startswith(_ZSTD_MAGIC)
        ):
            rendered[key] = {
                "__blob__": True,
                "size_bytes": len(value),
                "is_compressed": value.startswith(_ZSTD_MAGIC),
            }
        else:
            rendered[key] = json_safe(value)
    return rendered


def dataset_column_stats(
    ref: DatasetRef, top_k: int = 5, timeout_s: float = DEFAULT_QUERY_TIMEOUT_S
) -> list[dict]:
    """Per-column stats, with top values for low-cardinality string columns.

    The distinct-count threshold is what keeps this cheap: grouping a high-cardinality
    column in full would sort the whole column to show five values.
    """
    columns = dataset_schema(ref, timeout_s)
    if not columns:
        return columns
    conn = _open_ref(ref)
    try:
        names = [column["name"] for column in columns]
        aggregates = ", ".join(
            f"COUNT({_quote_ident(name)}) AS {_quote_ident('non_null_' + name)}, "
            f"APPROX_COUNT_DISTINCT({_quote_ident(name)}) AS "
            f"{_quote_ident('distinct_' + name)}"
            for name in names
        )
        totals = _execute(
            conn,
            f"SELECT COUNT(*), {aggregates} FROM {ref.reader_expression}",
            [],
            timeout_s,
        ).fetchone()
        rows_total = int(totals[0])
        for index, column in enumerate(columns):
            column["null_count"] = rows_total - int(totals[1 + index * 2])
            column["approx_distinct"] = int(totals[2 + index * 2])
            column["total_rows"] = rows_total
        for column in columns:
            column["top_values"] = []
            if not column["duckdb_type"].upper().startswith("VARCHAR"):
                continue
            if not 0 < column["approx_distinct"] <= 20:
                continue
            values = _execute(
                conn,
                f"SELECT {_quote_ident(column['name'])} AS value, COUNT(*) AS n "
                f"FROM {ref.reader_expression} "
                f"WHERE {_quote_ident(column['name'])} IS NOT NULL "
                f"GROUP BY 1 ORDER BY n DESC, value LIMIT ?",
                [top_k],
                timeout_s,
            ).fetchall()
            column["top_values"] = [
                {"value": json_safe(value), "count": int(count)}
                for value, count in values
            ]
        return columns
    except Exception as exc:
        raise _error(ref, exc) from exc
    finally:
        conn.close()


def dataset_blob(
    ref: DatasetRef,
    *,
    column: str,
    pk_col: str | None = None,
    pk_val: object | None = None,
    row_index: int | None = None,
    timeout_s: float = DEFAULT_QUERY_TIMEOUT_S,
) -> dict:
    """Fetch and decompress one BLOB cell, addressed by key or by row index.

    The result is capped: a 20 MB filing returned whole is a response nobody can use.
    """
    if not (pk_col and pk_val is not None) and row_index is None:
        raise DatasetError("either (pk_col, pk_val) or row_index must be provided")
    if row_index is not None and row_index < 0:
        raise DatasetError("row_index must be >= 0")

    conn = _open_ref(ref)
    try:
        ident = _quote_ident(column)
        if pk_col and pk_val is not None:
            sql = (
                f"SELECT {ident} FROM {ref.reader_expression} "
                f"WHERE {_quote_ident(pk_col)} = ? LIMIT 1"
            )
            row = _execute(conn, sql, [pk_val], timeout_s).fetchone()
        else:
            sql = f"SELECT {ident} FROM {ref.reader_expression} LIMIT 1 OFFSET ?"
            row = _execute(conn, sql, [row_index], timeout_s).fetchone()

        if not row or row[0] is None:
            raise DatasetError(f"no blob at {column!r} for the given locator")

        raw = bytes(row[0])
        compressed = raw.startswith(_ZSTD_MAGIC)
        if compressed:
            from edgar_sec.foundation.compression import decompress_payload

            try:
                expanded = decompress_payload(raw)
            except Exception as exc:
                raise DatasetError(f"blob could not be decompressed: {exc}") from exc
        else:
            expanded = raw

        text: str | None
        try:
            text = expanded.decode("utf-8")
        except UnicodeDecodeError:
            text = None

        return {
            "column": column,
            "is_compressed": compressed,
            "compressed_bytes": len(raw),
            "decompressed_bytes": len(expanded),
            "compression_ratio": round(len(expanded) / len(raw), 2) if raw else 1.0,
            "mime_type": _sniff_mime(text),
            "text": text,
            "preview": text[:MAX_BLOB_PREVIEW] if text else None,
        }
    except DatasetError:
        raise
    except Exception as exc:
        raise _error(ref, exc) from exc
    finally:
        conn.close()


def _sniff_mime(text: str | None) -> str:
    if not text:
        return "application/octet-stream"
    stripped = text.lstrip()
    lowered = stripped[:9].lower()
    if lowered.startswith(("<!doctype", "<html")):
        return "text/html"
    if stripped[0] in "{[":
        return "application/json"
    if stripped[0] in "#`|":
        return "text/markdown"
    return "text/plain"
