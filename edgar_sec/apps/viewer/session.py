"""One place a viewer query opens a DuckDB connection, and one way to time it.

Connections come from the sanctioned factory so they carry the cgroup-aware budget.
DuckDB has no statement timeout, so ``conn.interrupt`` is scheduled from outside and the
timer is cancelled on every path — a leaked one would interrupt the next query.
"""

from __future__ import annotations

import threading
from typing import Any

from edgar_sec.infra.storage.duckdb import connect

__all__ = ["DEFAULT_QUERY_TIMEOUT_S", "execute_bounded", "open_connection"]

DEFAULT_QUERY_TIMEOUT_S = 30.0
CONSOLE_TIMEOUT_S = 15.0


def open_connection() -> Any:
    """Open an in-memory, resource-budgeted DuckDB connection.

    In-memory so the viewer takes no lock or write handle on any artifact.
    """
    return connect()


def execute_bounded(conn, sql: str, params: list, timeout_s: float):
    """Execute a statement, interrupting it if it outruns ``timeout_s``."""
    timer = threading.Timer(timeout_s, conn.interrupt)
    timer.daemon = True
    timer.start()
    try:
        return conn.execute(sql, params)
    finally:
        timer.cancel()
