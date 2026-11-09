"""Run-scoped store for acquisition-time ephemeral target resolutions."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

_COLUMNS = (
    "target_id",
    "accession",
    "request_id",
    "target_role",
    "target_type",
    "document_type",
    "entry_id",
    "filename",
    "target_url",
    "sequence",
    "byte_size",
    "status",
    "status_reason",
    "outcome",
    "body_relative_path",
    "sha256",
)

_SCHEMA = """CREATE TABLE IF NOT EXISTS ephemeral_targets (
    target_id TEXT PRIMARY KEY,
    accession TEXT NOT NULL,
    request_id TEXT NOT NULL,
    target_role TEXT NOT NULL,
    target_type TEXT NOT NULL,
    document_type TEXT,
    entry_id TEXT,
    filename TEXT,
    target_url TEXT,
    sequence INTEGER,
    byte_size INTEGER,
    status TEXT NOT NULL,
    status_reason TEXT,
    outcome TEXT NOT NULL,
    body_relative_path TEXT,
    sha256 TEXT
)"""


_INSERT = (
    "INSERT OR REPLACE INTO ephemeral_targets ("
    "target_id, accession, request_id, target_role, target_type, document_type, "
    "entry_id, filename, target_url, sequence, byte_size, status, status_reason, "
    "outcome, body_relative_path, sha256"
    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


def record_ephemeral_targets(database_path: Path, rows: list[dict[str, Any]]) -> None:
    """Insert ephemeral resolutions into the run's own state store."""
    with sqlite3.connect(database_path) as connection:
        connection.execute(_SCHEMA)
        connection.executemany(
            _INSERT,
            [tuple(row.get(column) for column in _COLUMNS) for row in rows],
        )


def read_ephemeral_targets(database_path: Path) -> list[dict[str, Any]]:
    """Return recorded ephemeral resolutions, or none when the run has none."""
    if not database_path.is_file():
        return []
    with sqlite3.connect(
        f"file:{database_path.resolve()}?mode=ro", uri=True
    ) as connection:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'ephemeral_targets'"
        ).fetchone()
        if exists is None:
            return []
        connection.row_factory = sqlite3.Row
        return [
            dict(row)
            for row in connection.execute(
                "SELECT * FROM ephemeral_targets ORDER BY accession, request_id"
            )
        ]


__all__ = ["read_ephemeral_targets", "record_ephemeral_targets"]
