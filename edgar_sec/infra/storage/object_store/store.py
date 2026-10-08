"""SQLite persistence for global objects and session-local aliases."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import sqlite3
from pathlib import Path

from edgar_sec.infra.storage.object_store.models import SessionAlias, StoredObject
from edgar_sec.infra.storage.object_store.schema import SCHEMA_SQL


class ObjectStore:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA page_size = 8192")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize_schema(self) -> None:
        with self._connection() as connection:
            connection.executescript(SCHEMA_SQL)

    def touch_session(self, session_id: str, description: str = "") -> None:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO workspace_sessions (session_id, description)
                VALUES (?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    description = excluded.description,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (session_id, description),
            )

    def upsert_object(
        self,
        *,
        object_id: str,
        schema_name: str,
        data: str,
        parent_object_id: str | None = None,
    ) -> StoredObject:
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO objects (object_id, schema_name, parent_object_id, data)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(object_id) DO NOTHING
                """,
                (object_id, schema_name, parent_object_id, data),
            )
            row = connection.execute(
                "SELECT * FROM objects WHERE object_id = ?", (object_id,)
            ).fetchone()
            if row is None:
                raise RuntimeError("object insert did not produce a stored row")
            stored = self._stored_object(row)
            if (
                stored.schema_name != schema_name
                or stored.data != data
                or stored.parent_object_id != parent_object_id
            ):
                raise ValueError(
                    f"object {object_id!r} already exists with different payload"
                )
            return stored

    def get_object(self, object_id: str) -> StoredObject | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM objects WHERE object_id = ?", (object_id,)
            ).fetchone()
            return self._stored_object(row) if row is not None else None

    def upsert_alias(
        self, session_id: str, alias_name: str, target_id: str
    ) -> SessionAlias:
        with self._connection() as connection:
            self._touch_session(connection, session_id)
            if not self._target_exists(connection, target_id):
                raise ValueError(
                    f"Invalid alias target '{target_id}': entity not found"
                )
            connection.execute(
                """
                INSERT INTO object_session_aliases (
                    session_id, alias_name, target_id
                ) VALUES (?, ?, ?)
                ON CONFLICT(session_id, alias_name) DO UPDATE SET
                    target_id = excluded.target_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (session_id, alias_name, target_id),
            )
            row = connection.execute(
                """
                SELECT session_id, alias_name, target_id, created_at, updated_at
                FROM object_session_aliases
                WHERE session_id = ? AND alias_name = ?
                """,
                (session_id, alias_name),
            ).fetchone()
            if row is None:
                raise RuntimeError("alias insert did not produce a stored row")
            return self._session_alias(row)

    def get_alias_target(self, session_id: str, alias_name: str) -> str | None:
        with self._connection() as connection:
            self._touch_session(connection, session_id)
            row = connection.execute(
                """
                SELECT target_id FROM object_session_aliases
                WHERE session_id = ? AND alias_name = ?
                """,
                (session_id, alias_name),
            ).fetchone()
            return row["target_id"] if row is not None else None

    def list_aliases(self, session_id: str) -> dict[str, str]:
        with self._connection() as connection:
            self._touch_session(connection, session_id)
            rows = connection.execute(
                """
                SELECT alias_name, target_id FROM object_session_aliases
                WHERE session_id = ? ORDER BY alias_name
                """,
                (session_id,),
            ).fetchall()
            return {row["alias_name"]: row["target_id"] for row in rows}

    def drop_alias(self, session_id: str, alias_name: str) -> bool:
        with self._connection() as connection:
            self._touch_session(connection, session_id)
            cursor = connection.execute(
                """
                DELETE FROM object_session_aliases
                WHERE session_id = ? AND alias_name = ?
                """,
                (session_id, alias_name),
            )
            return cursor.rowcount > 0

    def clear_session(self, session_id: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "DELETE FROM workspace_sessions WHERE session_id = ?", (session_id,)
            )

    def clean_expired_sessions(self, max_age_seconds: int = 86400) -> int:
        with self._connection() as connection:
            cursor = connection.execute(
                """
                DELETE FROM workspace_sessions
                WHERE updated_at < datetime('now', ?)
                """,
                (f"-{max_age_seconds} seconds",),
            )
            return cursor.rowcount

    def set_active_session(self, session_id: str) -> None:
        with self._connection() as connection:
            self._touch_session(connection, session_id)
            connection.execute(
                """
                INSERT INTO active_workspace_session (id, session_id)
                VALUES (1, ?)
                ON CONFLICT(id) DO UPDATE SET
                    session_id = excluded.session_id,
                    switched_at = CURRENT_TIMESTAMP
                """,
                (session_id,),
            )

    def get_active_session(self) -> str:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT session_id FROM active_workspace_session WHERE id = 1"
            ).fetchone()
            if row is not None:
                session = connection.execute(
                    "SELECT session_id FROM workspace_sessions WHERE session_id = ?",
                    (row["session_id"],),
                ).fetchone()
                if session is not None:
                    self._touch_session(connection, session["session_id"])
                    return session["session_id"]
            self._touch_session(connection, "default")
            return "default"

    def list_sessions(self) -> list[str]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT session_id FROM workspace_sessions ORDER BY session_id"
            ).fetchall()
            return [row["session_id"] for row in rows]

    @staticmethod
    def _touch_session(connection: sqlite3.Connection, session_id: str) -> None:
        connection.execute(
            """
            INSERT INTO workspace_sessions (session_id)
            VALUES (?)
            ON CONFLICT(session_id) DO UPDATE SET updated_at = CURRENT_TIMESTAMP
            """,
            (session_id,),
        )

    @staticmethod
    def _target_exists(connection: sqlite3.Connection, target_id: str) -> bool:
        exists = connection.execute(
            "SELECT 1 FROM objects WHERE object_id = ?", (target_id,)
        ).fetchone()
        if exists is not None:
            return True
        cohort_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'cohorts'"
        ).fetchone()
        if cohort_table is None:
            return False
        return (
            connection.execute(
                "SELECT 1 FROM cohorts WHERE cohort_id = ?", (target_id,)
            ).fetchone()
            is not None
        )

    @staticmethod
    def _stored_object(row: sqlite3.Row) -> StoredObject:
        return StoredObject(
            object_id=row["object_id"],
            schema_name=row["schema_name"],
            parent_object_id=row["parent_object_id"],
            data=row["data"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _session_alias(row: sqlite3.Row) -> SessionAlias:
        return SessionAlias(
            session_id=row["session_id"],
            alias_name=row["alias_name"],
            target_id=row["target_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
