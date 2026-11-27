"""The test-side DuckDB connection seam."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.infra.storage.duckdb import Connection, connect

#: Test connections stamp 2 threads each: an unstamped pool runs ~5x
#: cores, and several per worker exhaust the host thread budget.
TEST_CONNECTION_THREADS = 2


def duckdb_connection(database: str | Path | None = None) -> Connection:
    """A test connection through the infra factory, the only test-side seam."""
    if database is None:
        return connect(threads=TEST_CONNECTION_THREADS)
    return connect(database=database, threads=TEST_CONNECTION_THREADS)


__all__ = [
    "duckdb_connection",
]
