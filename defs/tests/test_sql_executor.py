from __future__ import annotations

import sqlite3

import pytest

from defs.sql import CompiledQuery, DbApiBackend, SqlDialect, SqlExecutor


def statement(sql: str, *params: object) -> CompiledQuery:
    return CompiledQuery(sql=sql, params=tuple(params), dialect=SqlDialect.SQLITE)


def make_executor() -> SqlExecutor:
    return SqlExecutor(
        DbApiBackend(sqlite3.connect(":memory:"), dialect=SqlDialect.SQLITE)
    )


def test_executor_queries_rows_and_single_row():
    executor = make_executor()
    executor.exec(
        statement('CREATE TABLE "records" ("cik" TEXT PRIMARY KEY, "name" TEXT)')
    )
    executor.exec(
        statement('INSERT INTO "records" ("cik", "name") VALUES (?, ?)', "1", "One")
    )

    rows = executor.query(
        statement('SELECT "cik", "name" FROM "records" WHERE "cik" = ?', "1")
    )
    assert rows == [{"cik": "1", "name": "One"}]
    assert (
        executor.query_one(
            statement('SELECT "cik" FROM "records" WHERE "cik" = ?', "missing")
        )
        is None
    )


def test_executor_transaction_rolls_back_on_failure():
    executor = make_executor()
    executor.exec(statement('CREATE TABLE "records" ("cik" TEXT PRIMARY KEY)'))
    with pytest.raises(sqlite3.IntegrityError):
        executor.transaction(
            [
                statement('INSERT INTO "records" ("cik") VALUES (?)', "1"),
                statement('INSERT INTO "records" ("cik") VALUES (?)', "1"),
            ]
        )
    assert executor.query(statement('SELECT "cik" FROM "records"')) == []


def test_executor_rejects_uncompiled_or_wrong_dialect_statements():
    executor = make_executor()
    with pytest.raises(TypeError):
        executor.exec("CREATE TABLE records (cik TEXT)")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        executor.exec(CompiledQuery("SELECT 1", (), SqlDialect.DUCKDB))
