"""SQLite-backed HTTP response cache replacing loose per-URL files.

Stores zstd-compressed raw payloads keyed by SHA-256 of the URL,
plus an atomic failure ledger. Uses compiled SQL via defs/sql and
WAL mode for safe concurrent multi-process access.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import zstandard as zstd

from defs.sql import (
    ColumnDef,
    ColumnType,
    CreateTable,
    Delete,
    DoUpdate,
    Literal,
    NotNull,
    PrimaryKey,
    Select,
    SqlDialect,
    Star,
    Table,
    col,
    insert_values,
    make_sql_executor,
)
from defs.sql.expressions import Arithmetic, ArithmeticOp
from defs.sql.predicates import Membership, ValueList

_thread_local = threading.local()


def _get_compressor() -> zstd.ZstdCompressor:
    """Return the thread-local zstd compressor (C state is not thread-safe)."""
    compressor = getattr(_thread_local, "compressor", None)
    if compressor is None:
        compressor = zstd.ZstdCompressor()
        _thread_local.compressor = compressor
    return compressor


def _get_decompressor() -> zstd.ZstdDecompressor:
    """Return the thread-local zstd decompressor (C state is not thread-safe)."""
    decompressor = getattr(_thread_local, "decompressor", None)
    if decompressor is None:
        decompressor = zstd.ZstdDecompressor()
        _thread_local.decompressor = decompressor
    return decompressor


def _url_sha256(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


class SqlCache:
    """SQLite response cache with zstd-compressed payloads and failure ledger."""

    def __init__(self, cache_dir: str | Path) -> None:
        self.cache_dir = Path(cache_dir)
        self.db_path = self.cache_dir / "responses.sqlite"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.db_path.touch()
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.isolation_level = None
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        self._executor = make_sql_executor(conn, dialect=SqlDialect.SQLITE)
        self._create_tables()

    def _exec(self, statement) -> None:
        with self._lock:
            self._executor.exec(statement)
            self._executor.backend.connection.commit()

    def _query_one(self, statement) -> dict[str, Any] | None:
        with self._lock:
            return self._executor.query_one(statement)

    def _create_tables(self) -> None:
        self._exec(
            self._executor.compiler.compile(
                CreateTable(
                    table="url_responses",
                    columns=(
                        ColumnDef(
                            "url_sha256",
                            ColumnType.TEXT,
                            (PrimaryKey(), NotNull()),
                        ),
                        ColumnDef("url", ColumnType.TEXT, (NotNull(),)),
                        ColumnDef("payload", ColumnType.BLOB, (NotNull(),)),
                        ColumnDef("payload_sha256", ColumnType.TEXT, (NotNull(),)),
                        ColumnDef("byte_size", ColumnType.INT, (NotNull(),)),
                        ColumnDef("content_kind", ColumnType.TEXT, (NotNull(),)),
                        ColumnDef("fetched_at", ColumnType.TEXT, (NotNull(),)),
                    ),
                )
            )
        )
        self._exec(
            self._executor.compiler.compile(
                CreateTable(
                    table="url_failures",
                    columns=(
                        ColumnDef(
                            "url_sha256",
                            ColumnType.TEXT,
                            (PrimaryKey(), NotNull()),
                        ),
                        ColumnDef("url", ColumnType.TEXT, (NotNull(),)),
                        ColumnDef("failed_runs", ColumnType.INT, (NotNull(),)),
                        ColumnDef("last_kind", ColumnType.TEXT, (NotNull(),)),
                        ColumnDef("last_status", ColumnType.INT),
                        ColumnDef("last_detail", ColumnType.TEXT, (NotNull(),)),
                        ColumnDef("permanent", ColumnType.INT, (NotNull(),)),
                        ColumnDef("updated_at", ColumnType.TEXT, (NotNull(),)),
                    ),
                )
            )
        )

    def get(self, url: str) -> bytes | None:
        digest = _url_sha256(url)
        row = self._query_one(
            self._executor.compiler.compile(
                Select(
                    source=Table("url_responses"),
                    projection=(col("payload"),),
                    where=Membership(
                        value=col("url_sha256"),
                        source=ValueList((digest,)),
                    ),
                )
            )
        )
        if row is None:
            return None
        compressed = row["payload"]
        return _get_decompressor().decompress(bytes(compressed))

    def put(
        self,
        url: str,
        payload: bytes,
        sha256: str,
        byte_size: int,
        content_kind: str,
    ) -> None:
        digest = _url_sha256(url)
        compressed = _get_compressor().compress(payload)
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._exec(
            self._executor.compiler.compile(
                insert_values(
                    "url_responses",
                    {
                        "url_sha256": digest,
                        "url": url,
                        "payload": compressed,
                        "payload_sha256": sha256,
                        "byte_size": byte_size,
                        "content_kind": content_kind,
                        "fetched_at": now,
                    },
                    on_conflict=DoUpdate(
                        target=("url_sha256",),
                        assignments=(
                            ("url", Literal(url)),
                            ("payload", Literal(compressed)),
                            ("payload_sha256", Literal(sha256)),
                            ("byte_size", Literal(byte_size)),
                            ("content_kind", Literal(content_kind)),
                            ("fetched_at", Literal(now)),
                        ),
                    ),
                )
            )
        )

    def load_failure_entry(self, url: str) -> dict[str, Any] | None:
        digest = _url_sha256(url)
        row = self._query_one(
            self._executor.compiler.compile(
                Select(
                    source=Table("url_failures"),
                    projection=(Star(),),
                    where=Membership(
                        value=col("url_sha256"),
                        source=ValueList((digest,)),
                    ),
                )
            )
        )
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
    ) -> dict[str, Any] | None:
        digest = _url_sha256(url)
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._exec(
            self._executor.compiler.compile(
                insert_values(
                    "url_failures",
                    {
                        "url_sha256": digest,
                        "url": url,
                        "failed_runs": 1,
                        "last_kind": kind,
                        "last_status": status_code,
                        "last_detail": detail[:500],
                        "permanent": int(permanent),
                        "updated_at": now,
                    },
                    on_conflict=DoUpdate(
                        target=("url_sha256",),
                        assignments=(
                            (
                                "failed_runs",
                                Arithmetic(
                                    ArithmeticOp.ADD,
                                    (col("failed_runs"), Literal(1)),
                                ),
                            ),
                            ("last_kind", Literal(kind)),
                            ("last_status", Literal(status_code)),
                            ("last_detail", Literal(detail[:500])),
                            ("permanent", Literal(int(permanent))),
                            ("updated_at", Literal(now)),
                        ),
                    ),
                )
            )
        )
        return self.load_failure_entry(url)

    def clear_failure(self, url: str) -> None:
        digest = _url_sha256(url)
        self._exec(
            self._executor.compiler.compile(
                Delete(
                    table="url_failures",
                    where=Membership(
                        value=col("url_sha256"),
                        source=ValueList((digest,)),
                    ),
                )
            )
        )


def make_cache_store(cache_dir: str | Path | None = None) -> SqlCache | None:
    if not cache_dir:
        return None
    return SqlCache(cache_dir)


__all__ = ["SqlCache", "make_cache_store"]
