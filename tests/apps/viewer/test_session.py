"""Unit tests for apps.viewer.session.

These are thin on purpose: the module exists to be the single connection seam,
so what matters is that it delegates to ``infra.storage.duckdb.connect`` and
that its timeout wrapper always cancels.
"""

from __future__ import annotations

import contextlib
import threading
from typing import Any

import duckdb
import pytest

from edgar_sec.apps.viewer.session import (
    DEFAULT_QUERY_TIMEOUT_S,
    execute_bounded,
    open_connection,
)


def test_open_connection_produces_a_usable_budgeted_connection() -> None:
    conn = open_connection()
    try:
        # The resource budget is applied by the shared factory, so its settings
        # are observable on the connection the viewer hands out.
        assert int(conn.execute("SELECT current_setting('threads')").fetchone()[0]) >= 1
        assert conn.execute("SELECT 1").fetchone()[0] == 1
    finally:
        conn.close()


def test_execute_bounded_returns_the_result() -> None:
    conn = open_connection()
    try:
        assert execute_bounded(conn, "SELECT ?", [7], 5.0).fetchone()[0] == 7
    finally:
        conn.close()


def test_execute_bounded_cancels_its_timer_on_success() -> None:
    conn = open_connection()
    before = threading.active_count()
    try:
        execute_bounded(conn, "SELECT 1", [], 30.0)
    finally:
        conn.close()
    assert threading.active_count() <= before


def test_execute_bounded_cancels_its_timer_on_failure() -> None:
    """A leaked timer would interrupt whatever query ran next."""
    conn = open_connection()
    before = threading.active_count()
    try:
        with contextlib.suppress(duckdb.Error):
            execute_bounded(conn, "SELECT * FROM does_not_exist", [], 30.0)
    finally:
        conn.close()
    assert threading.active_count() <= before


def test_execute_bounded_interrupts_a_query_that_overruns() -> None:
    """A runaway query is cut off by conn.interrupt, not left to finish."""
    conn = open_connection()
    try:
        with pytest.raises(duckdb.Error, match="(?i)interrupt"):
            execute_bounded(conn, "SELECT count(*) FROM range(100000000000)", [], 0.5)
    finally:
        conn.close()


def test_default_timeout_is_positive() -> None:
    assert DEFAULT_QUERY_TIMEOUT_S > 0


def test_no_module_level_state_to_leak_between_requests() -> Any:
    """Two opens are independent connections, not a shared singleton."""
    first = open_connection()
    second = open_connection()
    try:
        assert first is not second
    finally:
        first.close()
        second.close()
