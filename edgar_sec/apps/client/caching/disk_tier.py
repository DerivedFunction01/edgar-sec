"""Disk tier for facade derivations: payload files behind a SQLite index.

Payload bytes live in content-keyed files, immutable once placed through
an atomic rename; the ledger — key, content hash, size, last access —
lives in one WAL SQLite database, mirroring the document cache's split.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from edgar_sec.foundation.hashing import sha256_bytes
from edgar_sec.infra.storage.atomic import atomic_write_bytes

_EVICTION_TARGET_FRACTION = 0.9


class DiskTier:
    """Bounded file-plus-ledger store for derived products too big for RAM."""

    def __init__(self, root: Path | str, budget_bytes: int) -> None:
        if budget_bytes < 1:
            raise ValueError("disk tier budget must be at least 1 byte")
        self._root = Path(root).resolve()
        self._files_dir = self._root / "files"
        self._files_dir.mkdir(parents=True, exist_ok=True)
        self._db_path = self._root / "index.sqlite"
        self._budget = budget_bytes
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        with self._lock:
            self._init_db()
            self._reap_orphans()

    @property
    def budget_bytes(self) -> int:
        """Byte budget enforced over distinct stored payloads."""
        return self._budget

    def get(self, kind: str, key: str) -> bytes | None:
        """Return the stored payload for a key, or None on a miss.

        A row whose file vanished or fails its content hash is a miss:
        the row is deleted and the caller falls through to recompute.
        """
        with self._lock:
            conn = self._connection()
            row = conn.execute(
                "SELECT content_sha256, byte_size FROM disk_entries"
                " WHERE kind = ? AND entry_key = ?",
                (kind, key),
            ).fetchone()
            if row is None:
                self._misses += 1
                return None
            sha, byte_size = str(row[0]), int(row[1])
            try:
                data = self._path_for(sha).read_bytes()
            except OSError:
                data = b""
            if len(data) != byte_size or sha256_bytes(data) != sha:
                self._delete_row(kind, key)
                self._unlink_if_unreferenced(sha)
                self._misses += 1
                return None
            conn.execute(
                "UPDATE disk_entries SET last_access = ?, hits = hits + 1"
                " WHERE kind = ? AND entry_key = ?",
                (time.time(), kind, key),
            )
            self._hits += 1
            return data

    def put(self, kind: str, key: str, payload: bytes, source_id: str = "") -> bool:
        """Place a payload and its index row, then enforce the byte budget."""
        if len(payload) > self._budget:
            return False
        sha = sha256_bytes(payload)
        path = self._path_for(sha)
        if not path.exists():
            atomic_write_bytes(path, payload)
        with self._lock:
            conn = self._connection()
            old = conn.execute(
                "SELECT content_sha256 FROM disk_entries"
                " WHERE kind = ? AND entry_key = ?",
                (kind, key),
            ).fetchone()
            conn.execute(
                "INSERT INTO disk_entries"
                " (kind, entry_key, content_sha256, byte_size, source_id,"
                " last_access, hits)"
                " VALUES (?, ?, ?, ?, ?, ?, 0)"
                " ON CONFLICT (kind, entry_key) DO UPDATE SET"
                " content_sha256 = excluded.content_sha256,"
                " byte_size = excluded.byte_size,"
                " source_id = excluded.source_id,"
                " last_access = excluded.last_access",
                (kind, key, sha, len(payload), source_id, time.time()),
            )
            if old is not None and str(old[0]) != sha:
                self._unlink_if_unreferenced(str(old[0]))
            self._enforce_budget()
            return True

    def delete(self, kind: str, key: str) -> None:
        """Drop one entry's row and, if unshared, its payload file."""
        with self._lock:
            conn = self._connection()
            row = conn.execute(
                "SELECT content_sha256 FROM disk_entries"
                " WHERE kind = ? AND entry_key = ?",
                (kind, key),
            ).fetchone()
            if row is None:
                return
            self._delete_row(kind, key)
            self._unlink_if_unreferenced(str(row[0]))

    def clear(self) -> None:
        """Drop every row and payload file and reset the counters."""
        with self._lock:
            conn = self._connection()
            conn.execute("DELETE FROM disk_entries")
            for path in self._iter_payload_files():
                path.unlink(missing_ok=True)
            self._hits = 0
            self._misses = 0
            self._evictions = 0

    def stats(self) -> dict[str, int]:
        """Return entry, byte, budget, and outcome counters for this tier."""
        with self._lock:
            conn = self._connection()
            entries = conn.execute("SELECT COUNT(*) FROM disk_entries").fetchone()
            return {
                "entries": int(entries[0]) if entries else 0,
                "current_bytes": self._total_bytes(conn),
                "budget_bytes": self._budget,
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
            }

    def close(self) -> None:
        """Close the index connection if one was opened."""
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self._db_path),
            timeout=30.0,
            check_same_thread=False,
            isolation_level=None,
        )
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def _connection(self) -> sqlite3.Connection:
        """The instance's one connection, opened lazily; caller holds the lock."""
        if self._conn is None:
            self._conn = self._connect()
        return self._conn

    def _init_db(self) -> None:
        self._connection().execute(
            """
            CREATE TABLE IF NOT EXISTS disk_entries (
                kind TEXT NOT NULL,
                entry_key TEXT NOT NULL,
                content_sha256 TEXT NOT NULL,
                byte_size INTEGER NOT NULL,
                source_id TEXT NOT NULL DEFAULT '',
                last_access REAL NOT NULL,
                hits INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (kind, entry_key)
            )
            """
        )

    def _path_for(self, sha: str) -> Path:
        return self._files_dir / sha[:2] / f"{sha}.bin"

    def _iter_payload_files(self) -> list[Path]:
        if not self._files_dir.exists():
            return []
        return [p for p in self._files_dir.rglob("*") if p.is_file()]

    def _reap_orphans(self) -> None:
        """Unlink payload files no index row references; caller holds the lock."""
        conn = self._connection()
        referenced = {
            str(row[0])
            for row in conn.execute("SELECT DISTINCT content_sha256 FROM disk_entries")
        }
        for path in self._iter_payload_files():
            if path.suffix == ".bin" and path.stem in referenced:
                continue
            path.unlink(missing_ok=True)

    def _total_bytes(self, conn: sqlite3.Connection) -> int:
        row = conn.execute(
            "SELECT COALESCE(SUM(byte_size), 0) FROM"
            " (SELECT DISTINCT content_sha256, byte_size FROM disk_entries)"
        ).fetchone()
        return int(row[0]) if row else 0

    def _delete_row(self, kind: str, key: str) -> None:
        self._connection().execute(
            "DELETE FROM disk_entries WHERE kind = ? AND entry_key = ?",
            (kind, key),
        )

    def _unlink_if_unreferenced(self, sha: str) -> None:
        row = (
            self._connection()
            .execute(
                "SELECT COUNT(*) FROM disk_entries WHERE content_sha256 = ?",
                (sha,),
            )
            .fetchone()
        )
        if row is not None and int(row[0]) == 0:
            self._path_for(sha).unlink(missing_ok=True)

    def _enforce_budget(self) -> None:
        """Evict coldest-by-last-access until at the target; caller holds the lock."""
        conn = self._connection()
        total = self._total_bytes(conn)
        if total <= self._budget:
            return
        target = int(self._budget * _EVICTION_TARGET_FRACTION)
        while total > target:
            row = conn.execute(
                "SELECT kind, entry_key, content_sha256, byte_size"
                " FROM disk_entries ORDER BY last_access ASC LIMIT 1"
            ).fetchone()
            if row is None:
                return
            kind, key, sha = str(row[0]), str(row[1]), str(row[2])
            shared = conn.execute(
                "SELECT COUNT(*) FROM disk_entries WHERE content_sha256 = ?",
                (sha,),
            ).fetchone()
            self._delete_row(kind, key)
            self._evictions += 1
            if shared is not None and int(shared[0]) <= 1:
                self._path_for(sha).unlink(missing_ok=True)
                total -= int(row[3])


__all__ = ["DiskTier"]
