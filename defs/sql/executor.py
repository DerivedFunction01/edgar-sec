"""Thin execution boundary for compiled SQL statements.

The executor deliberately knows nothing about phase schemas or CRUD semantics.
Phase-specific compiler/repository code builds :class:`CompiledQuery` values;
this module only binds parameters, executes them through a DB-API-compatible
connection, maps rows, and controls transactions.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from .compiler import QueryCompiler
from .models import CompiledQuery, SqlDialect


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
    """Small adapter for sqlite3, DuckDB, or compatible DB-API connections."""

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
        try:
            for statement in statements:
                self._cursor(statement).close()
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def close(self) -> None:
        self.connection.close()


class SqlExecutor:
    """Delegating facade matching the storage plan's TypeScript shape."""

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

    def close(self) -> None:
        self.backend.close()


__all__ = ["DbApiBackend", "DbApiConnection", "SqlBackend", "SqlExecutor"]
