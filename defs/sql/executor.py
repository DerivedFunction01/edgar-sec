"""Thin execution boundary for compiled SQL statements across SQLite and DuckDB.

The executor deliberately knows nothing about phase schemas or domain semantics.
Phase-specific compiler/repository code builds :class:`CompiledQuery` values;
this module binds parameters, executes them through DB-API-compatible
connections (sqlite3, DuckDB, PostgreSQL), maps rows, controls transactions,
and provides transparent zero-prefix view aliasing and attachment.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import duckdb

from .compiler import QueryCompiler
from .errors import CapabilityError
from .models import CompiledQuery, SqlDialect

_SQLITE_MAGIC = b"SQLite format 3\x00"
_DUCKDB_MAGIC = b"DUCK"
_ANALYTICAL_EXTENSIONS = frozenset(
    {".parquet", ".json", ".jsonl", ".csv", ".tsv", ".arrow"}
)


def detect_db_header(path: str | Path | os.PathLike[str]) -> str:
    """Inspect the first 16 bytes of a database file to identify the engine."""
    file_path = Path(path)
    if not file_path.is_file():
        return "unknown"
    try:
        with open(file_path, "rb") as f:
            header = f.read(16)
        if header.startswith(_SQLITE_MAGIC):
            return "sqlite"
        if _DUCKDB_MAGIC in header:
            return "duckdb"
    except OSError:
        return "unknown"
    return "unknown"


def is_analytical_dataset(path_or_glob: str | Path | os.PathLike[str]) -> bool:
    """Return True if the target represents an analytical file dataset (Parquet, JSONL, CSV)."""
    target = str(path_or_glob).lower()
    return any(
        target.endswith(ext) or f"{ext}*" in target for ext in _ANALYTICAL_EXTENSIONS
    )


@runtime_checkable
class DbApiConnection(Protocol):
    def cursor(self) -> Any: ...
    def commit(self) -> Any: ...
    def rollback(self) -> Any: ...
    def close(self) -> Any: ...


@runtime_checkable
class SqlBackend(Protocol):
    """Generic SQL execution contract implemented by database drivers."""

    compiler: QueryCompiler

    def query(self, statement: CompiledQuery) -> list[dict[str, Any]]: ...
    def query_one(self, statement: CompiledQuery) -> dict[str, Any] | None: ...
    def exec(self, statement: CompiledQuery) -> None: ...
    def transaction(self, statements: Sequence[CompiledQuery]) -> None: ...
    def close(self) -> None: ...


def _validate_statement(statement: CompiledQuery, dialect: SqlDialect) -> None:
    if not isinstance(statement, CompiledQuery):
        raise TypeError("SQL execution requires a CompiledQuery; compile SQL AST first")
    if statement.dialect is not dialect:
        raise ValueError(
            f"compiled statement uses {statement.dialect.value}, "
            f"but backend uses {dialect.value}"
        )


class DbApiBackend:
    """Universal adapter for sqlite3, DuckDB, or compatible DB-API connections."""

    def __init__(
        self, connection: DbApiConnection, *, dialect: SqlDialect | str
    ) -> None:
        self.connection = connection
        self.compiler = QueryCompiler(SqlDialect(dialect))

    def _cursor(self, statement: CompiledQuery) -> Any:
        _validate_statement(statement, self.compiler.dialect)
        cursor = self.connection.cursor()
        cursor.execute(statement.sql, statement.params)
        return cursor

    @staticmethod
    def _rows(cursor: Any) -> list[dict[str, Any]]:
        names = [column[0] for column in (cursor.description or ())]
        return [dict(zip(names, row)) for row in cursor.fetchall()]

    def query(self, statement: CompiledQuery) -> list[dict[str, Any]]:
        return self._rows(self._cursor(statement))

    def query_one(self, statement: CompiledQuery) -> dict[str, Any] | None:
        cursor = self._cursor(statement)
        row = cursor.fetchone()
        if row is None:
            return None
        names = [column[0] for column in (cursor.description or ())]
        return dict(zip(names, row))

    def exec(self, statement: CompiledQuery) -> None:
        self._cursor(statement).close()

    def transaction(self, statements: Sequence[CompiledQuery]) -> None:
        """Execute a batch of statements atomically with driver-aware transaction handling."""
        cursor = self.connection.cursor()
        if hasattr(cursor, "begin"):
            cursor.begin()
        try:
            for statement in statements:
                _validate_statement(statement, self.compiler.dialect)
                cursor.execute(statement.sql, statement.params)
            if hasattr(cursor, "commit"):
                cursor.commit()
            else:
                self.connection.commit()
        except Exception:
            if hasattr(cursor, "rollback"):
                cursor.rollback()
            else:
                self.connection.rollback()
            raise
        finally:
            cursor.close()

    def attach_sqlite(
        self,
        db_path: str | Path | os.PathLike[str],
        *,
        alias: str = "_sqlite_source",
        create_views: bool = True,
        read_only: bool = True,
    ) -> None:
        """Attach a SQLite database and optionally generate zero-prefix views in DuckDB."""
        path_str = str(db_path)
        if self.compiler.dialect is SqlDialect.DUCKDB:
            ro_clause = ", READ_ONLY" if read_only else ""
            self.connection.execute(
                f"ATTACH '{path_str}' AS {alias} (TYPE SQLITE{ro_clause});"
            )
            if create_views:
                tables = self.connection.execute("SHOW ALL TABLES;").fetchall()
                for database, _schema, name, _, _, _ in tables:
                    if database == alias:
                        self.connection.execute(
                            f'CREATE VIEW IF NOT EXISTS "{name}" AS SELECT * FROM {alias}."{name}";'
                        )
        elif self.compiler.dialect is SqlDialect.SQLITE:
            self.connection.execute(f"ATTACH DATABASE '{path_str}' AS {alias};")
        else:
            raise CapabilityError(
                "ATTACH SQLite database",
                self.compiler.dialect.value,
                "only DuckDB and SQLite backends support attaching SQLite databases",
            )

    def register_dataset_view(
        self,
        view_name: str,
        path_or_glob: str | Path | os.PathLike[str],
        *,
        format: str = "parquet",
    ) -> None:
        """Register an analytical file dataset (Parquet, JSONL, CSV) as a canonical SQL view."""
        if self.compiler.dialect is not SqlDialect.DUCKDB:
            raise CapabilityError(
                "analytical dataset views",
                self.compiler.dialect.value,
                f"use the DuckDB backend to query {format.upper()} files directly",
            )
        fmt = format.lower().strip(".")
        if fmt == "parquet":
            func = "read_parquet"
        elif fmt in ("json", "jsonl"):
            func = "read_json_auto"
        elif fmt in ("csv", "tsv"):
            func = "read_csv_auto"
        else:
            func = "read_parquet"
        path_str = str(path_or_glob)
        self.connection.execute(
            f"CREATE VIEW IF NOT EXISTS \"{view_name}\" AS SELECT * FROM {func}('{path_str}');"
        )

    def close(self) -> None:
        self.connection.close()


class SqlExecutor:
    """Delegating facade matching the repository SQL execution contract."""

    def __init__(self, backend: SqlBackend) -> None:
        self.backend = backend

    @property
    def compiler(self) -> QueryCompiler:
        return self.backend.compiler

    def query(self, statement: CompiledQuery) -> list[dict[str, Any]]:
        return self.backend.query(statement)

    def query_one(self, statement: CompiledQuery) -> dict[str, Any] | None:
        return self.backend.query_one(statement)

    def exec(self, statement: CompiledQuery) -> None:
        self.backend.exec(statement)

    def transaction(self, statements: Sequence[CompiledQuery]) -> None:
        self.backend.transaction(statements)

    def attach_sqlite(
        self,
        db_path: str | Path | os.PathLike[str],
        *,
        alias: str = "_sqlite_source",
        create_views: bool = True,
        read_only: bool = True,
    ) -> None:
        if hasattr(self.backend, "attach_sqlite"):
            self.backend.attach_sqlite(
                db_path, alias=alias, create_views=create_views, read_only=read_only
            )

    def register_dataset_view(
        self,
        view_name: str,
        path_or_glob: str | Path | os.PathLike[str],
        *,
        format: str = "parquet",
    ) -> None:
        if hasattr(self.backend, "register_dataset_view"):
            self.backend.register_dataset_view(view_name, path_or_glob, format=format)

    def close(self) -> None:
        self.backend.close()


def make_sql_executor(
    target: str | Path | os.PathLike[str] | DbApiConnection | None = None,
    *,
    dialect: SqlDialect | str | None = None,
    sqlite_sources: dict[str, str | Path] | None = None,
    dataset_views: dict[str, str | Path] | None = None,
) -> SqlExecutor:
    """Instantiate a unified SqlExecutor with driver auto-detection, view aliasing, and attachment."""
    resolved_dialect: SqlDialect | None = (
        SqlDialect(dialect) if dialect is not None else None
    )

    # 1. Target is an existing connection
    if target is not None and not isinstance(target, (str, Path, os.PathLike)):
        if resolved_dialect is None:
            resolved_dialect = (
                SqlDialect.DUCKDB
                if "duckdb" in type(target).__module__
                else SqlDialect.SQLITE
            )
        backend = DbApiBackend(target, dialect=resolved_dialect)
        executor = SqlExecutor(backend)

    # 2. Target is a path or None (in-memory)
    else:
        # Check if analytical dataset path/glob (Parquet, JSONL, CSV)
        if target is not None and is_analytical_dataset(target):
            if resolved_dialect is SqlDialect.SQLITE:
                raise CapabilityError(
                    "query analytical dataset",
                    "sqlite",
                    f"SQLite cannot query '{target}' directly; use DuckDB",
                )
            dcon = duckdb.connect()
            backend = DbApiBackend(dcon, dialect=SqlDialect.DUCKDB)
            view_name = (
                Path(str(target)).stem.replace("*", "").strip("._-") or "dataset"
            )
            backend.register_dataset_view(view_name, target)
            executor = SqlExecutor(backend)

        # Check if database file path
        elif target is not None and Path(str(target)).is_file():
            header_type = detect_db_header(target)
            if header_type == "sqlite":
                if resolved_dialect is SqlDialect.DUCKDB:
                    dcon = duckdb.connect()
                    backend = DbApiBackend(dcon, dialect=SqlDialect.DUCKDB)
                    backend.attach_sqlite(target, create_views=True)
                    executor = SqlExecutor(backend)
                else:
                    scon = sqlite3.connect(str(target))
                    backend = DbApiBackend(scon, dialect=SqlDialect.SQLITE)
                    executor = SqlExecutor(backend)
            elif header_type == "duckdb" or resolved_dialect is SqlDialect.DUCKDB:
                dcon = duckdb.connect(str(target))
                backend = DbApiBackend(dcon, dialect=SqlDialect.DUCKDB)
                executor = SqlExecutor(backend)
            else:
                scon = sqlite3.connect(str(target))
                backend = DbApiBackend(scon, dialect=SqlDialect.SQLITE)
                executor = SqlExecutor(backend)

        # In-memory default
        else:
            if resolved_dialect is SqlDialect.DUCKDB:
                dcon = duckdb.connect()
                backend = DbApiBackend(dcon, dialect=SqlDialect.DUCKDB)
                executor = SqlExecutor(backend)
            else:
                scon = sqlite3.connect(":memory:")
                backend = DbApiBackend(scon, dialect=SqlDialect.SQLITE)
                executor = SqlExecutor(backend)

    # Attach additional SQLite databases or register dataset views if requested
    if sqlite_sources:
        for alias, db_path in sqlite_sources.items():
            executor.attach_sqlite(db_path, alias=alias, create_views=True)

    if dataset_views:
        for view_name, path_or_glob in dataset_views.items():
            executor.register_dataset_view(view_name, path_or_glob)

    return executor


__all__ = [
    "DbApiBackend",
    "DbApiConnection",
    "SqlBackend",
    "SqlExecutor",
    "detect_db_header",
    "is_analytical_dataset",
    "make_sql_executor",
]
