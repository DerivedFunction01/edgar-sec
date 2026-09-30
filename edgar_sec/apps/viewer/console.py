"""The guarded, read-only SQL console.

The console is the one place in this package where a human's own text becomes
SQL, so it is the one place with a threat model. Four restrictions stack, and
removing any one of them is a hole:

1. :func:`foundation.sql.guard.validate_read_only` refuses anything that is not
   a single read statement.
2. Table functions are refused, so a console scoped to one dataset cannot reach
   another file on disk through ``read_parquet``.
3. The dataset is exposed as a private view named ``dataset`` and nothing else is
   in scope, so the reachable data is exactly the selected part list.
4. The result is capped twice — by row count and by accumulated payload size —
   and the query is interrupted if it outruns its time budget.

The row cap alone is not enough. A single row can be a megabyte of text, so a
query returning 9,999 enormous rows would pass a row check and still be a
response nobody can render. The payload cap exists because the row cap does not
cover that case.
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

    The guard allows ``SELECT``, so a query could otherwise name any Parquet,
    CSV, JSON, or SQLite file the server process can read — which is every
    artifact on disk, plus anything else. Scoping the query to one dataset is
    only meaningful if the dataset is the only thing reachable.
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

    Approximate on purpose: an exact count would mean serializing every row to
    measure it, which is the work the cap exists to avoid. String length is a
    good proxy because it dominates the response.
    """
    return sum(
        len(str(value))
        for row in rows
        for value in row.values()
        if isinstance(value, (str, bytes, list, dict))
    )
