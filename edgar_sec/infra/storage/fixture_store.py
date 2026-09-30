"""Append-only raw-payload SQLite store for Phase 2.5 fixtures."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Self
from urllib.parse import quote

import zstandard as zstd

from edgar_sec.infra.storage.payload_store import compress_payload, decompress_payload

_TABLE = "fixture_payloads"
_CREATE_TABLE = f"""
CREATE TABLE IF NOT EXISTS {_TABLE} (
    doc_id TEXT PRIMARY KEY NOT NULL,
    raw_payload BLOB NOT NULL
)
"""


class FixtureStoreError(RuntimeError):
    """A fixture store is missing, malformed, or could not be accessed."""


class FixtureStore:
    """Read or append compressed raw payloads keyed by document locator ID.

    Readers always use SQLite's read-only URI mode. A writable store creates
    only ``fixture_payloads`` and uses insert-ignore semantics so stored
    evidence cannot be replaced by a later response.
    """

    __slots__ = ("_connection", "_read_only", "db_path")

    def __init__(self, db_path: Path | str, *, read_only: bool = False) -> None:
        self.db_path = Path(db_path)
        self._read_only = read_only
        try:
            if read_only:
                if not self.db_path.is_file():
                    raise FixtureStoreError(
                        f"fixture database not found: {self.db_path}"
                    )
                uri = f"file:{quote(str(self.db_path.resolve()), safe='/')}?mode=ro"
                self._connection = sqlite3.connect(uri, uri=True)
            else:
                self.db_path.parent.mkdir(parents=True, exist_ok=True)
                self._connection = sqlite3.connect(str(self.db_path))
                objects = self._connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name != 'sqlite_sequence'"
                ).fetchall()
                if objects and not any(row[0] == _TABLE for row in objects):
                    raise FixtureStoreError(
                        f"database is not a fixture store (missing {_TABLE}): {self.db_path}"
                    )
                self._connection.execute(_CREATE_TABLE)
                self._connection.commit()
            self._validate_schema()
        except FixtureStoreError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise FixtureStoreError(
                f"cannot open fixture database {self.db_path}: {exc}"
            ) from exc

    def _validate_schema(self) -> None:
        columns = self._connection.execute(f"PRAGMA table_info({_TABLE})").fetchall()
        if [row[1] for row in columns] != ["doc_id", "raw_payload"]:
            raise FixtureStoreError(
                f"invalid {_TABLE} schema in {self.db_path}; expected doc_id, raw_payload"
            )

    def get(self, doc_id: str) -> bytes | None:
        """Return decompressed raw bytes for a document locator key."""
        try:
            row = self._connection.execute(
                f"SELECT raw_payload FROM {_TABLE} WHERE doc_id = ?", (doc_id,)
            ).fetchone()
            return None if row is None else decompress_payload(bytes(row[0]))
        except (sqlite3.Error, zstd.ZstdError) as exc:
            raise FixtureStoreError(
                f"cannot read fixture payload {doc_id}: {exc}"
            ) from exc

    def has(self, doc_id: str) -> bool:
        """Return whether the fixture contains a locator key."""
        try:
            return (
                self._connection.execute(
                    f"SELECT 1 FROM {_TABLE} WHERE doc_id = ?", (doc_id,)
                ).fetchone()
                is not None
            )
        except sqlite3.Error as exc:
            raise FixtureStoreError(f"cannot inspect fixture payloads: {exc}") from exc

    def locator_ids(self) -> tuple[str, ...]:
        """Return the fixture's locator keys in stable order."""
        try:
            rows = self._connection.execute(
                f"SELECT doc_id FROM {_TABLE} ORDER BY doc_id"
            ).fetchall()
            return tuple(str(row[0]) for row in rows)
        except sqlite3.Error as exc:
            raise FixtureStoreError(f"cannot list fixture payloads: {exc}") from exc

    def count(self) -> int:
        """Return the number of stored payloads."""
        try:
            return int(
                self._connection.execute(f"SELECT COUNT(*) FROM {_TABLE}").fetchone()[0]
            )
        except sqlite3.Error as exc:
            raise FixtureStoreError(f"cannot count fixture payloads: {exc}") from exc

    def put_many(self, payloads: list[tuple[str, bytes]]) -> int:
        """Append successful payloads and return the number newly inserted."""
        if self._read_only:
            raise FixtureStoreError("fixture store is read-only")
        if not payloads:
            return 0
        try:
            cursor = self._connection.executemany(
                f"INSERT OR IGNORE INTO {_TABLE} (doc_id, raw_payload) VALUES (?, ?)",
                [(doc_id, compress_payload(payload)) for doc_id, payload in payloads],
            )
            self._connection.commit()
            return cursor.rowcount
        except (sqlite3.Error, zstd.ZstdError) as exc:
            self._connection.rollback()
            raise FixtureStoreError(f"cannot append fixture payloads: {exc}") from exc

    def close(self) -> None:
        """Close the SQLite connection."""
        self._connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


__all__ = ["FixtureStore", "FixtureStoreError"]
