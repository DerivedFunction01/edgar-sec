"""Tests for the object store's shared SQLite schema."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from edgar_sec.infra.storage.object_store.store import ObjectStore


def test_schema_initializes_hardened_wal_database(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "shared" / "cohorts.sqlite")
    store.initialize_schema()

    connection = sqlite3.connect(store.db_path)
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA page_size").fetchone()[0] == 8192
        assert {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        } >= {
            "workspace_sessions",
            "active_workspace_session",
            "objects",
            "object_session_aliases",
        }
    finally:
        connection.close()


def test_each_connection_enables_foreign_keys_and_normal_sync(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "cohorts.sqlite")
    store.initialize_schema()

    connection = store._connect()
    try:
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA synchronous").fetchone()[0] == 1
    finally:
        connection.close()


def test_alias_schema_does_not_create_cohort_tables(tmp_path: Path) -> None:
    store = ObjectStore(tmp_path / "cohorts.sqlite")
    store.initialize_schema()

    connection = store._connect()
    try:
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'cohorts'"
            ).fetchone()
            is None
        )
    finally:
        connection.close()
