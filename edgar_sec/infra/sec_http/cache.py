"""SQLite-backed HTTP response cache with zstandard compression and failure ledger.

Responses are keyed by URL digest in an indexed WAL store, so concurrent
multi-worker access is safe. Expiry is selective: only ``.json`` paths carry a TTL.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from edgar_sec.foundation.compression import compress_payload, decompress_payload
from edgar_sec.foundation.runtime.settings.paths import DEFAULT_CACHE_TTL_S


def _url_sha256(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _expires_at(
    url: str,
    *,
    now: float | None = None,
    ttl_s: int = DEFAULT_CACHE_TTL_S,
    mutable: bool = False,
) -> str | None:
    """Expiry timestamp, or None when a response never expires.

    ``.json`` carries the TTL because archive documents are immutable; ``mutable``
    extends it to a URL whose extension would pin the response forever.
    """
    governed = mutable or urlsplit(url).path.lower().endswith(".json")
    if not governed or ttl_s <= 0:
        return None
    fetched = time.time() if now is None else now
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(fetched + ttl_s))


def _is_expired(expires_at: str | None, *, now: str | None = None) -> bool:
    return expires_at is not None and expires_at <= (now or _now())


class SqlCache:
    """SQLite response cache storing zstd-compressed payloads with failure ledger."""

    def __init__(
        self, cache_dir: str | Path, *, ttl_s: int = DEFAULT_CACHE_TTL_S
    ) -> None:
        self.cache_dir = Path(cache_dir).resolve()
        self.db_path = self.cache_dir / "responses.sqlite"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.ttl_s = ttl_s

        self.db_path.touch(exist_ok=True)
        self._con = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA journal_mode=WAL")
        self._con.execute("PRAGMA busy_timeout=5000")
        self._create_tables()

    def _create_tables(self) -> None:
        with self._lock, self._con:
            self._con.execute(
                """
                    CREATE TABLE IF NOT EXISTS url_responses (
                        url_sha256 TEXT PRIMARY KEY,
                        url TEXT NOT NULL,
                        payload BLOB NOT NULL,
                        payload_sha256 TEXT NOT NULL,
                        byte_size INTEGER NOT NULL,
                        content_kind TEXT NOT NULL,
                        fetched_at TEXT NOT NULL,
                        expires_at TEXT
                    )
                    """
            )
            self._con.execute(
                """
                    CREATE TABLE IF NOT EXISTS url_failures (
                        url_sha256 TEXT PRIMARY KEY,
                        url TEXT NOT NULL,
                        failed_runs INTEGER NOT NULL,
                        last_kind TEXT NOT NULL,
                        last_status INTEGER,
                        last_detail TEXT NOT NULL,
                        permanent INTEGER NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
            )

    def get(self, url: str) -> bytes | None:
        """Fetch and decompress response bytes if present and not expired."""
        digest = _url_sha256(url)
        with self._lock:
            cursor = self._con.execute(
                "SELECT payload, expires_at FROM url_responses WHERE url_sha256 = ?",
                (digest,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        if _is_expired(row["expires_at"]):
            return None
        compressed = bytes(row["payload"])
        return decompress_payload(compressed)

    def put(
        self,
        url: str,
        payload: bytes,
        sha256: str,
        byte_size: int,
        content_kind: str,
        *,
        mutable: bool = False,
    ) -> None:
        """Compress and persist response bytes."""
        digest = _url_sha256(url)
        compressed = compress_payload(payload)
        now = _now()
        expires_at = _expires_at(url, ttl_s=self.ttl_s, mutable=mutable)
        with self._lock, self._con:
            self._con.execute(
                """
                    INSERT INTO url_responses (
                        url_sha256, url, payload, payload_sha256, byte_size, content_kind, fetched_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(url_sha256) DO UPDATE SET
                        url = excluded.url,
                        payload = excluded.payload,
                        payload_sha256 = excluded.payload_sha256,
                        byte_size = excluded.byte_size,
                        content_kind = excluded.content_kind,
                        fetched_at = excluded.fetched_at,
                        expires_at = excluded.expires_at
                    """,
                (
                    digest,
                    url,
                    compressed,
                    sha256,
                    byte_size,
                    content_kind,
                    now,
                    expires_at,
                ),
            )

    def load_failure_entry(self, url: str) -> dict[str, object] | None:
        """Load failure history entry for a given URL."""
        digest = _url_sha256(url)
        with self._lock:
            cursor = self._con.execute(
                "SELECT * FROM url_failures WHERE url_sha256 = ?", (digest,)
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return {
            "url": row["url"],
            "failed_runs": row["failed_runs"],
            "last_kind": row["last_kind"],
            "last_status": row["last_status"],
            "last_detail": row["last_detail"],
            "permanent": bool(row["permanent"]),
            "updated_at": row["updated_at"],
        }

    def record_failure(
        self,
        url: str,
        *,
        kind: str,
        detail: str,
        status_code: int | None,
        permanent: bool,
    ) -> None:
        """Record or update a failed attempt in the failure ledger."""
        digest = _url_sha256(url)
        now = _now()
        with self._lock, self._con:
            self._con.execute(
                """
                    INSERT INTO url_failures (
                        url_sha256, url, failed_runs, last_kind, last_status, last_detail, permanent, updated_at
                    ) VALUES (?, ?, 1, ?, ?, ?, ?, ?)
                    ON CONFLICT(url_sha256) DO UPDATE SET
                        failed_runs = url_failures.failed_runs + 1,
                        last_kind = excluded.last_kind,
                        last_status = excluded.last_status,
                        last_detail = excluded.last_detail,
                        permanent = excluded.permanent,
                        updated_at = excluded.updated_at
                    """,
                (
                    digest,
                    url,
                    kind,
                    status_code,
                    detail[:500],
                    int(permanent),
                    now,
                ),
            )

    def clear_failure(self, url: str) -> None:
        """Clear failure entry when a subsequent attempt succeeds."""
        digest = _url_sha256(url)
        with self._lock, self._con:
            self._con.execute(
                "DELETE FROM url_failures WHERE url_sha256 = ?", (digest,)
            )

    def clear(
        self,
        *,
        url: str | None = None,
        url_pattern: str | None = None,
        cik: str | int | None = None,
        kind: str | None = None,
        older_than_s: int | float | None = None,
        expired_only: bool = False,
        clear_failures: bool = False,
        vacuum: bool = True,
    ) -> int:
        """Delete matching cached HTTP responses and optionally vacuum database."""
        conditions: list[str] = []
        params: list[object] = []

        if url is not None:
            conditions.append("url = ?")
            params.append(url)

        if url_pattern is not None:
            conditions.append("url LIKE ?")
            params.append(url_pattern)

        if cik is not None:
            s = str(cik).strip()
            padded = s.zfill(10)
            bare = str(int(s)) if s.isdigit() else s
            conditions.append("(url LIKE ? OR url LIKE ? OR url LIKE ?)")
            params.extend([f"%CIK{padded}%", f"%/data/{bare}/%", f"%/data/{padded}/%"])

        if kind is not None:
            conditions.append("content_kind = ?")
            params.append(kind)

        if older_than_s is not None and older_than_s > 0:
            cutoff = time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - older_than_s)
            )
            conditions.append("fetched_at <= ?")
            params.append(cutoff)

        if expired_only:
            conditions.append("expires_at IS NOT NULL AND expires_at <= ?")
            params.append(_now())

        where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"DELETE FROM url_responses {where_sql}"

        with self._lock:
            with self._con:
                cursor = self._con.execute(query, tuple(params))
                deleted = cursor.rowcount

                if clear_failures:
                    fail_conds: list[str] = []
                    fail_params: list[object] = []
                    if url is not None:
                        fail_conds.append("url = ?")
                        fail_params.append(url)
                    if url_pattern is not None:
                        fail_conds.append("url LIKE ?")
                        fail_params.append(url_pattern)
                    if cik is not None:
                        s = str(cik).strip()
                        padded = s.zfill(10)
                        bare = str(int(s)) if s.isdigit() else s
                        fail_conds.append("(url LIKE ? OR url LIKE ? OR url LIKE ?)")
                        fail_params.extend(
                            [f"%CIK{padded}%", f"%/data/{bare}/%", f"%/data/{padded}/%"]
                        )
                    fail_where = (
                        f"WHERE {' AND '.join(fail_conds)}" if fail_conds else ""
                    )
                    fail_query = f"DELETE FROM url_failures {fail_where}"
                    self._con.execute(fail_query, tuple(fail_params))

            if vacuum and deleted > 0:
                self._con.execute("VACUUM")

        return deleted

    def vacuum(self) -> None:
        """Reclaim free space and defragment SQLite database file."""
        with self._lock:
            self._con.execute("VACUUM")

    def stats(self) -> dict[str, object]:
        """Return cache storage statistics."""
        with self._lock:
            row = self._con.execute(
                """
                SELECT
                    COUNT(*) as count,
                    COALESCE(SUM(byte_size), 0) as total_bytes,
                    COALESCE(SUM(LENGTH(payload)), 0) as compressed_bytes,
                    MIN(fetched_at) as oldest,
                    MAX(fetched_at) as newest
                FROM url_responses
                """
            ).fetchone()
            fail_row = self._con.execute(
                "SELECT COUNT(*) as count FROM url_failures"
            ).fetchone()
            expired_row = self._con.execute(
                "SELECT COUNT(*) as count FROM url_responses WHERE expires_at IS NOT NULL AND expires_at <= ?",
                (_now(),),
            ).fetchone()
        db_size = self.db_path.stat().st_size if self.db_path.is_file() else 0
        return {
            "responses_count": row["count"] if row else 0,
            "failures_count": fail_row["count"] if fail_row else 0,
            "expired_count": expired_row["count"] if expired_row else 0,
            "total_bytes": row["total_bytes"] if row else 0,
            "compressed_bytes": row["compressed_bytes"] if row else 0,
            "oldest_fetched_at": row["oldest"] if row else None,
            "newest_fetched_at": row["newest"] if row else None,
            "db_size_bytes": db_size,
        }

    def close(self) -> None:
        with self._lock:
            self._con.close()


def make_cache_store(
    cache_dir: str | Path | None, *, ttl_s: int = DEFAULT_CACHE_TTL_S
) -> SqlCache | None:
    if cache_dir is None:
        return None
    return SqlCache(cache_dir, ttl_s=ttl_s)


__all__ = ["SqlCache", "make_cache_store"]
