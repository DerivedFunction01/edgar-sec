"""The test-side DuckDB connection seam."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.infra.storage.duckdb import Connection, connect


def duckdb_connection(database: str | Path | None = None) -> Connection:
    """A test connection through the infra factory, the only test-side seam."""
    return connect() if database is None else connect(database=database)


__all__ = [
    "duckdb_connection",
]
