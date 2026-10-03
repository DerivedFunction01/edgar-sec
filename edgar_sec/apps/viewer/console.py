"""The guarded, read-only SQL console.

Table functions are refused so a query scoped to one dataset cannot reach another file
on disk, and the row cap alone is not enough: a megabyte-per-row result passes a row
check and is still unrenderable, so the payload cap covers that.
"""

from __future__ import annotations

import time
from collections.abc import Iterator

from edgar_sec.apps.viewer.datasets import DatasetError, DatasetRef
from edgar_sec.apps.viewer.session import (
    CONSOLE_TIMEOUT_S,
)
from edgar_sec.apps.viewer.session import (
    execute_bounded as _execute,
)
from edgar_sec.apps.viewer.session import (
    open_connection as _open,
)
from edgar_sec.foundation.serialization import json_safe
from edgar_sec.foundation.sql.guard import SqlGuardError, validate_read_only

__all__ = [
    "MAX_PAYLOAD_BYTES",
    "MAX_SQL_ROWS",
    "run_dataset_sql",
]

MAX_SQL_ROWS = 10_000
MAX_PAYLOAD_BYTES = 8 * 1024 * 1024
_FETCH_BATCH = 500

# The single relation a console query may name. Matching on the lowercase
# substring catches every spelling of the call.
_FORBIDDEN_FUNCTIONS = ("read_parquet", "read_json", "read_csv", "sqlite_scan")


def _check_no_table_functions(query: str) -> None:
    """Refuse table functions in console input.

    The guard allows ``SELECT``, which would otherwise reach any readable file.
    """
    lowered = query.lower()
    for name in _FORBIDDEN_FUNCTIONS:
        if name in lowered:
            raise DatasetError(
                f"table function {name!r} is not allowed in console queries"
            )


def run_dataset_sql(
    ref: DatasetRef,
    query: str,
    *,
    timeout_s: float = CONSOLE_TIMEOUT_S,
) -> dict:
    """Run one guarded read against one dataset and return a bounded result set."""
    if ref.fmt == "duckdb":
        raise DatasetError("SQL console is disabled for native DuckDB files")
    try:
        validated = validate_read_only(query)
    except SqlGuardError as exc:
        raise DatasetError(str(exc)) from exc
    _check_no_table_functions(validated)

    # The LIMIT is applied by the wrapper, not by trusting the user's query, so
    # the cap holds even if the query contains its own unbounded subquery.
    wrapped = f"SELECT * FROM (\n{validated}\n) __viewer_console LIMIT {MAX_SQL_ROWS}"

    conn = _open()
    started = time.monotonic()
    try:
        ref.prepare_connection(conn)
        conn.execute(f"CREATE VIEW dataset AS SELECT * FROM {ref.reader_expression}")
        result = _execute(conn, wrapped, [], timeout_s)
        columns = [str(description[0]) for description in result.description]
        rows: list[dict] = []
        truncated = False
        for batch in _batches(result):
            for row in batch:
                rows.append(json_safe(dict(zip(columns, row, strict=True))))
                if len(rows) >= MAX_SQL_ROWS:
                    truncated = True
                    break
            if truncated:
                break
            if _payload_bytes(rows[-_FETCH_BATCH:]) > MAX_PAYLOAD_BYTES:
                truncated = True
                break
        return {
            "columns": columns,
            "rows": rows,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 2),
            "truncated": truncated,
        }
    except DatasetError:
        raise
    except Exception as exc:
        if "INTERRUPT" in str(exc).upper():
            raise DatasetError(
                f"query exceeded {timeout_s:g}s and was interrupted"
            ) from exc
        raise DatasetError(str(exc)) from exc
    finally:
        conn.close()


def _batches(result) -> Iterator[list]:
    """Yield result rows in batches rather than materializing the whole set."""
    while True:
        batch = result.fetchmany(_FETCH_BATCH)
        if not batch:
            return
        yield batch


def _payload_bytes(rows: list[dict]) -> int:
    """Approximate the serialized size of the most recent batch.

    Approximate on purpose: an exact count would serialize every row, which is the work
    the cap exists to avoid.
    """
    return sum(
        len(str(value))
        for row in rows
        for value in row.values()
        if isinstance(value, (str, bytes, list, dict))
    )
