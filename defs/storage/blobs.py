"""Document blob storage access primitives.

Provides engine-neutral (SQLite & DuckDB) streaming iterators over document blobs
compiled via the defs.sql AST compiler and executed through SqlExecutor.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

import duckdb

from defs.sql.executor import DbApiBackend, SqlExecutor, detect_db_header
from defs.sql.expressions import Aggregate, Column
from defs.sql.models import AggregateFunction, Identifier, SqlDialect
from defs.sql.predicates import Membership, ValueList
from defs.sql.relations import OrderBy, Select, Table


class DocumentBlob(NamedTuple):
    """Raw document record fetched from blob storage."""

    doc_id: str
    document_path: str
    mime_type: str
    raw_payload: bytes


def _open_sql_executor(db_path: Path) -> tuple[SqlExecutor, object]:
    """Open a dialect-appropriate SqlExecutor and raw connection for SQLite or DuckDB."""
    engine = detect_db_header(db_path)
    if engine == "duckdb":
        conn = duckdb.connect(str(db_path), read_only=True)
        backend = DbApiBackend(conn, dialect=SqlDialect.DUCKDB)
    else:
        conn = sqlite3.connect(str(db_path))
        backend = DbApiBackend(conn, dialect=SqlDialect.SQLITE)
    return SqlExecutor(backend), conn


def stream_document_blobs(
    db_path: Path | str,
    *,
    mime_types: tuple[str, ...] = ("text/html", "application/xhtml+xml"),
    limit: int | None = None,
    offset: int = 0,
    batch_size: int = 250,
) -> Iterator[DocumentBlob]:
    """Stream document blobs sequentially across SQLite or DuckDB using compiled SQL AST queries."""
    target_path = Path(db_path)
    if not target_path.exists():
        raise FileNotFoundError(f"Blob database not found at {target_path}")

    executor, conn = _open_sql_executor(target_path)
    try:
        current_offset = offset
        fetched_total = 0

        while True:
            current_limit = (
                min(batch_size, limit - fetched_total)
                if limit is not None
                else batch_size
            )
            if current_limit <= 0:
                break

            stmt = Select(
                source=Table("document_blobs"),
                projection=(
                    Column(Identifier("doc_id")),
                    Column(Identifier("document_path")),
                    Column(Identifier("mime_type")),
                    Column(Identifier("raw_payload")),
                ),
                where=Membership(
                    value=Column(Identifier("mime_type")),
                    source=ValueList(tuple(mime_types)),
                ),
                order_by=(OrderBy(Column(Identifier("doc_id"))),),
                limit=current_limit,
                offset=current_offset,
            )

            compiled = executor.compiler.compile(stmt)
            rows = executor.query(compiled)

            if not rows:
                break

            for row in rows:
                yield DocumentBlob(
                    doc_id=str(row["doc_id"]),
                    document_path=str(row["document_path"]),
                    mime_type=str(row["mime_type"]),
                    raw_payload=bytes(row["raw_payload"]),
                )
                fetched_total += 1
                if limit is not None and fetched_total >= limit:
                    return

            current_offset += len(rows)
            if len(rows) < current_limit:
                break
    finally:
        conn.close()


def count_document_blobs(
    db_path: Path | str,
    *,
    mime_types: tuple[str, ...] = ("text/html", "application/xhtml+xml"),
) -> int:
    """Return total count of matching document blobs using compiled SQL AST."""
    target_path = Path(db_path)
    if not target_path.exists():
        return 0

    executor, conn = _open_sql_executor(target_path)
    try:
        stmt = Select(
            source=Table("document_blobs"),
            projection=(
                Aggregate(
                    function=AggregateFunction.COUNT,
                    argument=Column(Identifier("doc_id")),
                ),
            ),
            where=Membership(
                value=Column(Identifier("mime_type")),
                source=ValueList(tuple(mime_types)),
            ),
        )
        compiled = executor.compiler.compile(stmt)
        row = executor.query_one(compiled)
        if not row:
            return 0
        val = next(iter(row.values()))
        return int(val) if val is not None else 0
    finally:
        conn.close()


__all__ = [
    "DocumentBlob",
    "count_document_blobs",
    "stream_document_blobs",
]
