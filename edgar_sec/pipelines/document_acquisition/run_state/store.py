from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import quote

from edgar_sec.pipelines.document_acquisition.run_state.schema import SCHEMA_VERSION


class RunStateError(RuntimeError):
    pass


def _connect(database_path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        uri = f"file:{quote(str(database_path.resolve()), safe='/')}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, isolation_level=None)
    else:
        connection = sqlite3.connect(database_path, isolation_level=None)
    connection.execute("PRAGMA foreign_keys = ON")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        connection.close()
        raise RunStateError("SQLite foreign-key enforcement is unavailable")
    return connection


def _require_schema(connection: sqlite3.Connection) -> None:
    if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
        raise RunStateError("unsupported run-state schema version")


__all__ = [
    "RunStateError",
]
