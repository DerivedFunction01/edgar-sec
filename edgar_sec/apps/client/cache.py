"""SQLite-backed document cache for interactive fast-path document retrieval.

Stores lazy document payloads indexed by accession, CIK, and form, providing
selective invalidation and on-demand export to flat files or ZIP archives.
"""

from __future__ import annotations

import sqlite3
import threading
import time
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from edgar_sec.foundation.hashing import sha256_bytes
from edgar_sec.foundation.runtime.paths import resolve_paths
from edgar_sec.foundation.runtime.resources import derive_resources
from edgar_sec.foundation.runtime.settings.runtime import resolve_read_batch_size


class DocumentCache:
    """Thread-safe SQLite store for acquired filing document payloads."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        artifacts_root: Path | str | None = None,
    ) -> None:
        if db_path is not None:
            self.db_path = Path(db_path).resolve()
        elif artifacts_root is not None:
            self.db_path = Path(artifacts_root).resolve() / "cache" / "documents.sqlite"
        else:
            root = resolve_paths().artifacts_root
            self.db_path = root / "cache" / "documents.sqlite"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
            check_same_thread=False,
            isolation_level=None,
        )
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS cached_documents (
                        accession TEXT NOT NULL,
                        cik INTEGER NOT NULL,
                        form TEXT NOT NULL,
                        filename TEXT NOT NULL,
                        content_type TEXT NOT NULL,
                        sha256 TEXT NOT NULL,
                        byte_size INTEGER NOT NULL,
                        content BLOB NOT NULL,
                        cached_at TEXT NOT NULL,
                        PRIMARY KEY (accession, filename)
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_cached_docs_cik "
                    "ON cached_documents (cik)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_cached_docs_accession "
                    "ON cached_documents (accession)"
                )
            finally:
                conn.close()

    def get(self, accession: str, filename: str) -> bytes | None:
        """Retrieve cached document bytes by accession and filename."""
        conn = self._connect()
        try:
            cursor = conn.execute(
                "SELECT content FROM cached_documents "
                "WHERE accession = ? AND filename = ?",
                (accession, filename),
            )
            row = cursor.fetchone()
            return bytes(row[0]) if row is not None else None
        finally:
            conn.close()

    def put(
        self,
        accession: str,
        cik: int | str,
        form: str,
        filename: str,
        content: bytes,
        content_type: str = "text/plain",
    ) -> None:
        """Insert or update a document payload in the cache."""
        cik_int = int(cik)
        digest = sha256_bytes(content)
        byte_size = len(content)
        now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT INTO cached_documents (
                        accession, cik, form, filename, content_type,
                        sha256, byte_size, content, cached_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(accession, filename) DO UPDATE SET
                        content_type = excluded.content_type,
                        sha256 = excluded.sha256,
                        byte_size = excluded.byte_size,
                        content = excluded.content,
                        cached_at = excluded.cached_at
                    """,
                    (
                        accession,
                        cik_int,
                        form,
                        filename,
                        content_type,
                        digest,
                        byte_size,
                        content,
                        now_iso,
                    ),
                )
            finally:
                conn.close()

    def clear(
        self,
        accession: str | None = None,
        cik: int | str | None = None,
    ) -> int:
        """Delete cached documents by accession, CIK, or clear all."""
        with self._lock:
            conn = self._connect()
            try:
                if accession is not None:
                    cursor = conn.execute(
                        "DELETE FROM cached_documents WHERE accession = ?",
                        (accession,),
                    )
                elif cik is not None:
                    cursor = conn.execute(
                        "DELETE FROM cached_documents WHERE cik = ?",
                        (int(cik),),
                    )
                else:
                    cursor = conn.execute("DELETE FROM cached_documents")
                return cursor.rowcount
            finally:
                conn.close()

    def count(
        self,
        accession: str | None = None,
        cik: int | str | None = None,
    ) -> int:
        """Count cached documents matching the given filter."""
        conn = self._connect()
        try:
            if accession is not None:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM cached_documents WHERE accession = ?",
                    (accession,),
                )
            elif cik is not None:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM cached_documents WHERE cik = ?",
                    (int(cik),),
                )
            else:
                cursor = conn.execute("SELECT COUNT(*) FROM cached_documents")
            row = cursor.fetchone()
            return int(row[0]) if row else 0
        finally:
            conn.close()

    def export_files(
        self,
        destination: Path | str,
        accession: str | None = None,
        cik: int | str | None = None,
    ) -> list[Path]:
        """Export cached documents into flat files under destination."""
        dest_dir = Path(destination).resolve()
        dest_dir.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        written: list[Path] = []
        batch_size = resolve_read_batch_size()
        try:
            if accession is not None:
                cursor = conn.execute(
                    "SELECT accession, filename, content FROM cached_documents "
                    "WHERE accession = ?",
                    (accession,),
                )
            elif cik is not None:
                cursor = conn.execute(
                    "SELECT accession, filename, content FROM cached_documents "
                    "WHERE cik = ?",
                    (int(cik),),
                )
            else:
                cursor = conn.execute(
                    "SELECT accession, filename, content FROM cached_documents"
                )
            while rows := cursor.fetchmany(batch_size):
                for acc, fname, content in rows:
                    out_path = dest_dir / acc / fname
                    out_path.parent.mkdir(parents=True, exist_ok=True)
                    out_path.write_bytes(content)
                    written.append(out_path)
            return written
        finally:
            conn.close()

    def export_zip(
        self,
        zip_path: Path | str,
        accession: str | None = None,
        cik: int | str | None = None,
    ) -> Path:
        """Export matching cached documents into a single ZIP archive."""
        target_zip = Path(zip_path).resolve()
        target_zip.parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        batch_size = resolve_read_batch_size()
        try:
            if accession is not None:
                cursor = conn.execute(
                    "SELECT accession, filename, content FROM cached_documents "
                    "WHERE accession = ?",
                    (accession,),
                )
            elif cik is not None:
                cursor = conn.execute(
                    "SELECT accession, filename, content FROM cached_documents "
                    "WHERE cik = ?",
                    (int(cik),),
                )
            else:
                cursor = conn.execute(
                    "SELECT accession, filename, content FROM cached_documents"
                )
            with zipfile.ZipFile(
                target_zip, mode="w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                while rows := cursor.fetchmany(batch_size):
                    for acc, fname, content in rows:
                        archive.writestr(f"{acc}/{fname}", content)
            return target_zip
        finally:
            conn.close()


def get_default_cache(
    artifacts_root: Path | str | None = None,
) -> DocumentCache:
    """Return DocumentCache for default or specified artifacts root."""
    if artifacts_root is not None:
        return DocumentCache(artifacts_root=artifacts_root)
    global _DEFAULT_CACHE
    if _DEFAULT_CACHE is None:
        with _CACHE_LOCK:
            if _DEFAULT_CACHE is None:
                _DEFAULT_CACHE = DocumentCache()
    return _DEFAULT_CACHE


_DEFAULT_CACHE: DocumentCache | None = None
_CACHE_LOCK = threading.Lock()
