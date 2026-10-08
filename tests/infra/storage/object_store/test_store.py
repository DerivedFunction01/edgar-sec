"""Tests for immutable objects, aliases, and session cleanup."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from edgar_sec.infra.storage.object_store.store import ObjectStore


def _store(tmp_path: Path) -> ObjectStore:
    store = ObjectStore(tmp_path / "cohorts.sqlite")
    store.initialize_schema()
    return store


def test_objects_are_global_immutable_and_parent_linked(tmp_path: Path) -> None:
    store = _store(tmp_path)
    parent = store.upsert_object(
        object_id="parent", schema_name="expr", data='{"op":"leaf"}'
    )
    first = store.upsert_object(
        object_id="child",
        schema_name="expr",
        data='{"op":"join"}',
        parent_object_id=parent.object_id,
    )
    assert (
        store.upsert_object(
            object_id="child",
            schema_name="expr",
            data='{"op":"join"}',
            parent_object_id=parent.object_id,
        )
        == first
    )
    assert store.get_object("child") == first

    store.touch_session("one")
    store.touch_session("two")
    assert store.upsert_alias("one", "A", "child").target_id == "child"
    assert store.upsert_alias("two", "A", "child").target_id == "child"
    with pytest.raises(ValueError, match="different payload"):
        store.upsert_object(
            object_id="child", schema_name="expr", data='{"op":"other"}'
        )


def test_aliases_validate_object_and_existing_cohort_targets(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="entity not found"):
        store.upsert_alias("session", "x", "missing")

    with sqlite3.connect(store.db_path) as connection:
        connection.execute("CREATE TABLE cohorts (cohort_id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO cohorts VALUES ('cohort-1')")

    alias = store.upsert_alias("session", "x", "cohort-1")
    assert alias.target_id == "cohort-1"
    assert store.get_alias_target("session", "x") == "cohort-1"


def test_alias_upsert_moves_pointer_and_touch_updates_session(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert_object(object_id="a", schema_name="expr", data="a")
    store.upsert_object(object_id="b", schema_name="expr", data="b")
    original = store.upsert_alias("session", "x", "a")
    moved = store.upsert_alias("session", "x", "b")

    assert moved.target_id == "b"
    assert moved.created_at == original.created_at
    assert store.list_aliases("session") == {"x": "b"}
    assert store.drop_alias("session", "x") is True
    assert store.drop_alias("session", "x") is False
    assert store.list_aliases("session") == {}


def test_touch_session_updates_timestamp_and_description(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.touch_session("session", "initial")
    with sqlite3.connect(store.db_path) as connection:
        connection.execute(
            "UPDATE workspace_sessions SET updated_at = '2000-01-01 00:00:00' "
            "WHERE session_id = 'session'"
        )

    store.touch_session("session", "refreshed")
    with sqlite3.connect(store.db_path) as connection:
        row = connection.execute(
            "SELECT description, updated_at FROM workspace_sessions "
            "WHERE session_id = 'session'"
        ).fetchone()
    assert row[0] == "refreshed"
    assert row[1] != "2000-01-01 00:00:00"


def test_active_session_defaults_and_clear_preserves_objects(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.get_active_session() == "default"
    assert store.list_sessions() == ["default"]

    store.upsert_object(object_id="global", schema_name="expr", data="payload")
    store.upsert_alias("work", "x", "global")
    store.set_active_session("work")
    assert store.get_active_session() == "work"

    store.clear_session("work")
    assert store.get_active_session() == "default"
    assert store.get_object("global") is not None
    assert store.list_aliases("work") == {}


def test_expired_session_cleanup_removes_aliases_not_objects(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.upsert_object(object_id="global", schema_name="expr", data="payload")
    store.upsert_alias("expired", "x", "global")
    store.set_active_session("expired")
    with sqlite3.connect(store.db_path) as connection:
        connection.execute(
            "UPDATE workspace_sessions SET updated_at = datetime('now', '-2 days') "
            "WHERE session_id = 'expired'"
        )

    assert store.clean_expired_sessions() == 1
    assert store.get_active_session() == "default"
    assert store.list_aliases("expired") == {}
    assert store.get_object("global") is not None
