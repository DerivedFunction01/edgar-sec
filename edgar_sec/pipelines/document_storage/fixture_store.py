"""Append-only raw-payload SQLite store for fixtures."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Self
from urllib.parse import quote

import zstandard as zstd

from edgar_sec.domain.document.models import RawDocumentBlob
from edgar_sec.foundation.compression import compress_payload, decompress_payload

_TABLE = "fixture_payloads"
_CREATE_TABLE = f"""
CREATE TABLE IF NOT EXISTS {_TABLE} (
    doc_id TEXT PRIMARY KEY NOT NULL,
    raw_payload BLOB NOT NULL
)
"""

#: A payload key is a one-way digest, so document metadata must be stored beside
#: it to reconstruct the ``DocumentLocator`` needed by review and normalization.
_DOCUMENTS_TABLE = "document_blobs"
_CREATE_DOCUMENTS_TABLE = f"""
CREATE TABLE IF NOT EXISTS {_DOCUMENTS_TABLE} (
    doc_id TEXT PRIMARY KEY NOT NULL,
    accession TEXT NOT NULL,
    document_path TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    mime_type TEXT NOT NULL,
    raw_payload_sha256 TEXT NOT NULL
)
"""

#: Filing form is stored separately to keep the document metadata schema stable.
#: Callers can use fixture-manifest metadata when this table is absent.
_FORMS_TABLE = "fixture_document_forms"
_CREATE_FORMS_TABLE = f"""
CREATE TABLE IF NOT EXISTS {_FORMS_TABLE} (
    doc_id TEXT PRIMARY KEY NOT NULL,
    form TEXT NOT NULL
)
"""

_DOCUMENT_COLUMNS = (
    "doc_id",
    "accession",
    "document_path",
    "byte_size",
    "mime_type",
    "raw_payload_sha256",
)


class FixtureStoreError(RuntimeError):
    """A fixture store is missing, malformed, or could not be accessed."""


class FixtureStore:
    """Read or append compressed raw payloads keyed by document locator id.

    Readers use SQLite's read-only URI; a writable store creates only
    ``fixture_payloads`` and insert-ignores, so evidence is never replaced.
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
                self._connection.execute(_CREATE_DOCUMENTS_TABLE)
                self._connection.execute(_CREATE_FORMS_TABLE)
                self._connection.commit()
            self._validate_schema()
        except FixtureStoreError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise FixtureStoreError(
                f"cannot open fixture database {self.db_path}: {exc}"
            ) from exc

    def _table_exists(self, table: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        return row is not None

    def _validate_schema(self) -> None:
        columns = self._connection.execute(f"PRAGMA table_info({_TABLE})").fetchall()
        if [row[1] for row in columns] != ["doc_id", "raw_payload"]:
            raise FixtureStoreError(
                f"invalid {_TABLE} schema in {self.db_path}; expected doc_id, raw_payload"
            )
        # A fixture recorded before document metadata existed has no ``document_blobs``.
        # That is an incomplete store, not a corrupt one, so reads report "no metadata".
        if self._table_exists(_DOCUMENTS_TABLE):
            document_columns = self._connection.execute(
                f"PRAGMA table_info({_DOCUMENTS_TABLE})"
            ).fetchall()
            if [row[1] for row in document_columns] != list(_DOCUMENT_COLUMNS):
                raise FixtureStoreError(
                    f"invalid {_DOCUMENTS_TABLE} schema in {self.db_path}; "
                    f"expected {', '.join(_DOCUMENT_COLUMNS)}"
                )

    @property
    def has_document_metadata(self) -> bool:
        """Whether this fixture records per-document identity and hashes."""
        return self._table_exists(_DOCUMENTS_TABLE)

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

    def has_document(self, doc_id: str) -> bool:
        """Return whether the fixture records metadata for a locator key."""
        if not self._table_exists(_DOCUMENTS_TABLE):
            return False
        try:
            return (
                self._connection.execute(
                    f"SELECT 1 FROM {_DOCUMENTS_TABLE} WHERE doc_id = ?", (doc_id,)
                ).fetchone()
                is not None
            )
        except sqlite3.Error as exc:
            raise FixtureStoreError(
                f"cannot inspect fixture document metadata: {exc}"
            ) from exc

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

    # --- document metadata ------------------------------------------------

    def put_documents(
        self,
        documents: Sequence[RawDocumentBlob],
        forms: Mapping[str, str] | None = None,
    ) -> int:
        """Record per-document identity and source hashes, idempotently.

        Called for every locator, not only newly fetched payloads: that is the repair
        path for a fixture recorded before this table existed, and it costs no network.
        """
        if self._read_only:
            raise FixtureStoreError("fixture store is read-only")
        # Forms are written independently, so a forms-only caller must still get them.
        if not documents and not forms:
            return 0
        try:
            self._connection.executemany(
                f"INSERT OR IGNORE INTO {_DOCUMENTS_TABLE} "
                f"({', '.join(_DOCUMENT_COLUMNS)}) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        document.doc_id,
                        document.accession,
                        document.document_path,
                        document.byte_size,
                        document.mime_type,
                        document.raw_payload_sha256,
                    )
                    for document in documents
                ],
            )
            if forms:
                self._connection.executemany(
                    f"INSERT OR IGNORE INTO {_FORMS_TABLE} (doc_id, form) VALUES (?, ?)",
                    [
                        (doc_id, form)
                        for doc_id, form in forms.items()
                        if doc_id and form
                    ],
                )
            self._connection.commit()
            return len(documents)
        except sqlite3.Error as exc:
            self._connection.rollback()
            raise FixtureStoreError(
                f"cannot record fixture document metadata: {exc}"
            ) from exc

    def documents(
        self,
        *,
        ids: Sequence[str] = (),
        extensions: Sequence[str] = (),
        limit: int | None = None,
    ) -> tuple[RawDocumentBlob, ...]:
        """Return stored document metadata, always ordered by document id.

        Ordering is the selection contract: ``limit`` takes the first N ids deterministically.
        """
        if not self._table_exists(_DOCUMENTS_TABLE):
            return ()
        clauses: list[str] = []
        parameters: list[Any] = []
        if ids:
            placeholders = ", ".join("?" for _ in ids)
            clauses.append(f"doc_id IN ({placeholders})")
            parameters.extend(ids)
        for extension in extensions:
            clauses.append("document_path LIKE ?")
            parameters.append(f"%.{extension.lstrip('.')}")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        suffix = " LIMIT ?" if limit is not None else ""
        if limit is not None:
            parameters.append(int(limit))
        try:
            rows = self._connection.execute(
                f"SELECT {', '.join(_DOCUMENT_COLUMNS)} FROM {_DOCUMENTS_TABLE}"
                f"{where} ORDER BY doc_id{suffix}",
                parameters,
            ).fetchall()
        except sqlite3.Error as exc:
            raise FixtureStoreError(
                f"cannot read fixture document metadata: {exc}"
            ) from exc
        return tuple(
            RawDocumentBlob.from_row(dict(zip(_DOCUMENT_COLUMNS, row, strict=True)))
            for row in rows
        )

    def document_forms(self) -> dict[str, str]:
        """Return the recorded per-document form for every document that has one."""
        if not self._table_exists(_FORMS_TABLE):
            return {}
        try:
            rows = self._connection.execute(
                f"SELECT doc_id, form FROM {_FORMS_TABLE} ORDER BY doc_id"
            ).fetchall()
        except sqlite3.Error as exc:
            raise FixtureStoreError(
                f"cannot read fixture document forms: {exc}"
            ) from exc
        return {str(row[0]): str(row[1]) for row in rows}

    def close(self) -> None:
        """Close the SQLite connection."""
        self._connection.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


__all__ = ["FixtureStore", "FixtureStoreError"]
