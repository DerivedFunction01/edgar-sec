"""Content-addressed raw-payload store for the offline document fetch path.

A worker needs the exact bytes SEC returned for a document, both to replay a
run without network and to render a review bundle. Those bytes are immutable
and identified twice over: by *what* was fetched (``document_locator_key``) and
by *what it contained* (``blob_hash``). Storing both is what makes the store
safe to share — a caller can assert it got the bytes it expected, and two runs
that fetched the same document agree without a round trip.

Scope, deliberately narrow: this store holds raw payloads and the minimal
metadata needed to identify them. It is **not** a processing database. Nothing
reads rows out of it to compute a result; the Parquet chunk path is the only
route from payload to normalized artifact, and this store feeds it bytes.

Layout: one SQLite file per fixture id, so a fixture can be copied, deleted, or
attached independently, and so a test never touches the shared tree.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Self

import zstandard as zstd

_thread_local = threading.local()

#: Raw payloads are content-addressed; this table is append-only in practice
#: because a re-fetch of the same bytes must be a no-op, not a mutation.
_PAYLOADS_TABLE = "document_payloads"

_CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {_PAYLOADS_TABLE} (
    document_locator_key TEXT NOT NULL,
    blob_hash            TEXT NOT NULL,
    accession            TEXT NOT NULL,
    document_path        TEXT NOT NULL,
    byte_size            INTEGER NOT NULL,
    mime_type            TEXT,
    raw_payload          BLOB NOT NULL,
    stored_at            TEXT NOT NULL,
    PRIMARY KEY (document_locator_key, blob_hash)
)
"""

_CREATE_INDEX_SQL = f"""
CREATE INDEX IF NOT EXISTS idx_{_PAYLOADS_TABLE}_locator
    ON {_PAYLOADS_TABLE} (document_locator_key)
"""


class PayloadStoreError(RuntimeError):
    """The payload store could not satisfy a read or write."""


def _get_compressor() -> zstd.ZstdCompressor:
    compressor = getattr(_thread_local, "compressor", None)
    if compressor is None:
        compressor = zstd.ZstdCompressor()
        _thread_local.compressor = compressor
    return compressor


def _get_decompressor() -> zstd.ZstdDecompressor:
    decompressor = getattr(_thread_local, "decompressor", None)
    if decompressor is None:
        decompressor = zstd.ZstdDecompressor()
        _thread_local.decompressor = decompressor
    return decompressor


def compress_payload(payload: bytes) -> bytes:
    """Compress one raw payload for storage."""
    return _get_compressor().compress(payload)


def decompress_payload(blob: bytes) -> bytes:
    """Decompress one stored raw payload."""
    return _get_decompressor().decompress(blob)


@dataclass(frozen=True, slots=True)
class PayloadRecord:
    """One stored raw payload's identifying metadata, without its bytes."""

    document_locator_key: str
    blob_hash: str
    accession: str
    document_path: str
    byte_size: int
    mime_type: str | None
    stored_at: str


class PayloadStore:
    """Append-only, content-addressed store of raw document payloads."""

    __slots__ = ("_con", "_lock", "db_path")

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._con = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.execute("PRAGMA busy_timeout=5000")
        self._con.execute("PRAGMA synchronous=NORMAL")
        with self._lock:
            self._con.execute(_CREATE_TABLE_SQL)
            self._con.execute(_CREATE_INDEX_SQL)
            self._con.commit()

    # --- writes ----------------------------------------------------------

    def put(
        self,
        *,
        document_locator_key: str,
        blob_hash: str,
        accession: str,
        document_path: str,
        raw_payload: bytes,
        mime_type: str | None = None,
        stored_at: str,
    ) -> bool:
        """Store one raw payload. Returns False when identical bytes exist.

        Idempotent by construction: the primary key is
        ``(document_locator_key, blob_hash)``, so storing the same bytes twice
        is a no-op rather than a duplicate row or an overwrite.
        """
        with self._lock:
            cursor = self._con.execute(
                f"INSERT OR IGNORE INTO {_PAYLOADS_TABLE} ("
                "document_locator_key, blob_hash, accession, document_path, "
                "byte_size, mime_type, raw_payload, stored_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    document_locator_key,
                    blob_hash,
                    accession,
                    document_path,
                    len(raw_payload),
                    mime_type,
                    compress_payload(raw_payload),
                    stored_at,
                ),
            )
            self._con.commit()
            return cursor.rowcount > 0

    # --- reads -----------------------------------------------------------

    def get(
        self, document_locator_key: str, blob_hash: str | None = None
    ) -> bytes | None:
        """Return the stored bytes, or None when the payload is absent.

        With no ``blob_hash`` the most recently stored revision wins, which is
        what a replay wants when the source document was re-fetched and changed.
        """
        with self._lock:
            if blob_hash is None:
                row = self._con.execute(
                    f"SELECT raw_payload FROM {_PAYLOADS_TABLE} "
                    "WHERE document_locator_key = ? "
                    "ORDER BY stored_at DESC, rowid DESC LIMIT 1",
                    (document_locator_key,),
                ).fetchone()
            else:
                row = self._con.execute(
                    f"SELECT raw_payload FROM {_PAYLOADS_TABLE} "
                    "WHERE document_locator_key = ? AND blob_hash = ?",
                    (document_locator_key, blob_hash),
                ).fetchone()
        if row is None:
            return None
        return decompress_payload(row["raw_payload"])

    def has(self, document_locator_key: str, blob_hash: str | None = None) -> bool:
        """Return whether a payload is present."""
        with self._lock:
            if blob_hash is None:
                row = self._con.execute(
                    f"SELECT 1 FROM {_PAYLOADS_TABLE} "
                    "WHERE document_locator_key = ? LIMIT 1",
                    (document_locator_key,),
                ).fetchone()
            else:
                row = self._con.execute(
                    f"SELECT 1 FROM {_PAYLOADS_TABLE} "
                    "WHERE document_locator_key = ? AND blob_hash = ?",
                    (document_locator_key, blob_hash),
                ).fetchone()
        return row is not None

    def get_record(
        self, document_locator_key: str, blob_hash: str | None = None
    ) -> PayloadRecord | None:
        """Return the identifying metadata without decompressing the bytes."""
        with self._lock:
            if blob_hash is None:
                row = self._con.execute(
                    f"SELECT * FROM {_PAYLOADS_TABLE} "
                    "WHERE document_locator_key = ? "
                    "ORDER BY stored_at DESC, rowid DESC LIMIT 1",
                    (document_locator_key,),
                ).fetchone()
            else:
                row = self._con.execute(
                    f"SELECT * FROM {_PAYLOADS_TABLE} "
                    "WHERE document_locator_key = ? AND blob_hash = ?",
                    (document_locator_key, blob_hash),
                ).fetchone()
        if row is None:
            return None
        return PayloadRecord(
            document_locator_key=str(row["document_locator_key"]),
            blob_hash=str(row["blob_hash"]),
            accession=str(row["accession"]),
            document_path=str(row["document_path"]),
            byte_size=int(row["byte_size"]),
            mime_type=None if row["mime_type"] is None else str(row["mime_type"]),
            stored_at=str(row["stored_at"]),
        )

    def locator_keys(self) -> tuple[str, ...]:
        """Return every document locator key present in the store."""
        with self._lock:
            rows = self._con.execute(
                f"SELECT DISTINCT document_locator_key FROM {_PAYLOADS_TABLE} "
                "ORDER BY document_locator_key"
            ).fetchall()
        return tuple(str(row["document_locator_key"]) for row in rows)

    def count(self) -> int:
        """Return the number of stored payload rows."""
        with self._lock:
            row = self._con.execute(
                f"SELECT COUNT(*) AS n FROM {_PAYLOADS_TABLE}"
            ).fetchone()
        return int(row["n"])

    def close(self) -> None:
        """Close the connection. Safe to call more than once."""
        with self._lock:
            self._con.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


class PayloadStoreReader:
    """Read-only, fail-open view over a payload store.

    Consumers that can tolerate a missing fixture (the review tool, a status
    command) should not have to distinguish "no fixture" from "store
    corrupted". Every read returns ``None`` instead of raising, so a missing or
    unreadable store degrades the caller rather than failing the run.
    """

    __slots__ = ("_store",)

    def __init__(self, db_path: Path | str) -> None:
        self._store: PayloadStore | None = None
        try:
            if Path(db_path).is_file():
                self._store = PayloadStore(db_path)
        except (sqlite3.Error, OSError):
            self._store = None

    @property
    def available(self) -> bool:
        """Return whether a usable store was found."""
        return self._store is not None

    def get(
        self, document_locator_key: str, blob_hash: str | None = None
    ) -> bytes | None:
        """Return stored bytes, or None when absent or unreadable."""
        if self._store is None:
            return None
        try:
            return self._store.get(document_locator_key, blob_hash)
        except (sqlite3.Error, OSError, zstd.ZstdError, PayloadStoreError):
            return None

    def has(self, document_locator_key: str, blob_hash: str | None = None) -> bool:
        """Return whether a payload is readable, fail-open."""
        if self._store is None:
            return False
        try:
            return self._store.has(document_locator_key, blob_hash)
        except (sqlite3.Error, OSError):
            return False

    def get_record(
        self, document_locator_key: str, blob_hash: str | None = None
    ) -> PayloadRecord | None:
        """Return payload metadata, or None when absent or unreadable."""
        if self._store is None:
            return None
        try:
            return self._store.get_record(document_locator_key, blob_hash)
        except (sqlite3.Error, OSError):
            return None

    def close(self) -> None:
        """Close the underlying store when one was opened."""
        if self._store is not None:
            self._store.close()
            self._store = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()


def make_payload_store(db_path: Path | str) -> PayloadStore:
    """Create or open a writable payload store."""
    return PayloadStore(db_path)


def make_payload_store_reader(db_path: Path | str) -> PayloadStoreReader:
    """Open a fail-open read-only view over a payload store."""
    return PayloadStoreReader(db_path)


__all__ = [
    "PayloadRecord",
    "PayloadStore",
    "PayloadStoreError",
    "PayloadStoreReader",
    "compress_payload",
    "decompress_payload",
    "make_payload_store",
    "make_payload_store_reader",
]
