"""One place a viewer query opens a DuckDB connection, and one way to time it.

Shared by :mod:`apps.viewer.datasets` and :mod:`apps.viewer.console` so neither
owns the other's connection lifecycle.

Two constraints are enforced here rather than at each call site:

**Every connection is budgeted.** It comes from ``infra.storage.duckdb.connect``,
the single sanctioned seam, so it carries the cgroup-aware thread and memory
limits. A viewer is an interactive tool, but "interactive" does not mean
"unbounded" — one wide page over a large snapshot is exactly the scan that
should spill to the temp directory rather than be OOM-killed.

**Every statement is interruptible.** DuckDB has no statement timeout, so a
query that would run for an hour is bounded from outside by scheduling
``conn.interrupt``. The timer is a daemon and is cancelled on every path,
including the error path: a leaked timer would fire an interrupt against
whichever query happened to be running next.
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

    In-memory because the viewer must not take a lock on, or a write handle to,
    any artifact. Artifacts are bound afterwards as table-function arguments,
    which only ever reads.
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
