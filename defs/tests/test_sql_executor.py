from __future__ import annotations

import sqlite3
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from defs.sql import (
    CapabilityError,
    CompiledQuery,
    DbApiBackend,
    SqlDialect,
    SqlExecutor,
    detect_db_header,
    is_analytical_dataset,
    make_sql_executor,
)


def sqlite_statement(sql: str, *params: object) -> CompiledQuery:
    return CompiledQuery(sql=sql, params=tuple(params), dialect=SqlDialect.SQLITE)


def duckdb_statement(sql: str, *params: object) -> CompiledQuery:
    return CompiledQuery(sql=sql, params=tuple(params), dialect=SqlDialect.DUCKDB)


def test_sqlite_executor_queries_rows_and_single_row():
    executor = SqlExecutor(
        DbApiBackend(sqlite3.connect(":memory:"), dialect=SqlDialect.SQLITE)
    )
    executor.exec(
        sqlite_statement('CREATE TABLE "records" ("cik" TEXT PRIMARY KEY, "name" TEXT)')
    )
    executor.exec(
        sqlite_statement(
            'INSERT INTO "records" ("cik", "name") VALUES (?, ?)', "1", "One"
        )
    )

    rows = executor.query(
        sqlite_statement('SELECT "cik", "name" FROM "records" WHERE "cik" = ?', "1")
    )
    assert rows == [{"cik": "1", "name": "One"}]
    assert (
        executor.query_one(
            sqlite_statement('SELECT "cik" FROM "records" WHERE "cik" = ?', "missing")
        )
        is None
    )
    executor.close()


def test_sqlite_executor_transaction_rolls_back_on_failure():
    executor = SqlExecutor(
        DbApiBackend(sqlite3.connect(":memory:"), dialect=SqlDialect.SQLITE)
    )
    executor.exec(sqlite_statement('CREATE TABLE "records" ("cik" TEXT PRIMARY KEY)'))
    with pytest.raises(sqlite3.IntegrityError):
        executor.transaction(
            [
                sqlite_statement('INSERT INTO "records" ("cik") VALUES (?)', "1"),
                sqlite_statement('INSERT INTO "records" ("cik") VALUES (?)', "1"),
            ]
        )
    assert executor.query(sqlite_statement('SELECT "cik" FROM "records"')) == []
    executor.close()


def test_duckdb_executor_queries_rows_and_single_row():
    dcon = duckdb.connect()
    executor = SqlExecutor(DbApiBackend(dcon, dialect=SqlDialect.DUCKDB))

    executor.exec(
        duckdb_statement(
            'CREATE TABLE "records" ("cik" VARCHAR PRIMARY KEY, "name" VARCHAR)'
        )
    )
    executor.exec(
        duckdb_statement(
            'INSERT INTO "records" ("cik", "name") VALUES (?, ?)', "0000000001", "Apple"
        )
    )

    rows = executor.query(
        duckdb_statement(
            'SELECT "cik", "name" FROM "records" WHERE "cik" = ?', "0000000001"
        )
    )
    assert rows == [{"cik": "0000000001", "name": "Apple"}]

    one = executor.query_one(
        duckdb_statement('SELECT "name" FROM "records" WHERE "cik" = ?', "0000000001")
    )
    assert one == {"name": "Apple"}
    executor.close()


def test_duckdb_executor_transaction_rolls_back_on_failure():
    dcon = duckdb.connect()
    executor = SqlExecutor(DbApiBackend(dcon, dialect=SqlDialect.DUCKDB))

    executor.exec(duckdb_statement('CREATE TABLE "items" ("id" INTEGER PRIMARY KEY)'))
    with pytest.raises((duckdb.ConstraintException, duckdb.Error)):
        executor.transaction(
            [
                duckdb_statement('INSERT INTO "items" ("id") VALUES (?)', 1),
                duckdb_statement(
                    'INSERT INTO "items" ("id") VALUES (?)', 1
                ),  # duplicate primary key
            ]
        )

    rows = executor.query(duckdb_statement('SELECT * FROM "items"'))
    assert rows == []
    executor.close()


def test_magic_header_detection(tmp_path: Path):
    # SQLite file
    sqlite_file = tmp_path / "test_sqlite.db"
    scon = sqlite3.connect(sqlite_file)
    scon.execute("CREATE TABLE t (x INT)")
    scon.commit()
    scon.close()
    assert detect_db_header(sqlite_file) == "sqlite"

    # DuckDB file
    duck_file = tmp_path / "test_duck.duckdb"
    dcon = duckdb.connect(str(duck_file))
    dcon.execute("CREATE TABLE t (x INT)")
    dcon.close()
    assert detect_db_header(duck_file) == "duckdb"

    # Non-existent or empty
    non_existent = tmp_path / "missing.db"
    assert detect_db_header(non_existent) == "unknown"


def test_is_analytical_dataset():
    assert is_analytical_dataset("manifests/filing_targets/final/*.parquet")
    assert is_analytical_dataset("data.jsonl")
    assert is_analytical_dataset("data.csv")
    assert not is_analytical_dataset("filing_documents.db")
    assert not is_analytical_dataset("filing_documents.sqlite")


def test_duckdb_auto_attach_sqlite_with_zero_prefix_views(tmp_path: Path):
    sqlite_file = tmp_path / "filings.db"
    scon = sqlite3.connect(sqlite_file)
    scon.execute("CREATE TABLE parsed_documents (doc_id TEXT PRIMARY KEY, text TEXT)")
    scon.execute("INSERT INTO parsed_documents VALUES ('doc_1', 'clean text payload')")
    scon.commit()
    scon.close()

    # Create DuckDB executor with attached SQLite
    executor = make_sql_executor(
        sqlite_file,
        dialect=SqlDialect.DUCKDB,
    )

    # Query zero-prefix view without engine-specific prefixes
    rows = executor.query(
        duckdb_statement(
            "SELECT doc_id, text FROM parsed_documents WHERE doc_id = ?", "doc_1"
        )
    )
    assert rows == [{"doc_id": "doc_1", "text": "clean text payload"}]
    executor.close()


def test_duckdb_register_dataset_view(tmp_path: Path):
    parquet_file = tmp_path / "sample.parquet"
    table = pa.Table.from_pydict(
        {"cik": ["0000000001", "0000000002"], "name": ["Alpha", "Beta"]}
    )
    pq.write_table(table, parquet_file)

    executor = make_sql_executor(
        parquet_file,
        dialect=SqlDialect.DUCKDB,
    )

    # Query auto-registered view
    rows = executor.query(duckdb_statement("SELECT cik, name FROM sample ORDER BY cik"))
    assert rows == [
        {"cik": "0000000001", "name": "Alpha"},
        {"cik": "0000000002", "name": "Beta"},
    ]
    executor.close()


def test_sqlite_rejects_parquet_dataset(tmp_path: Path):
    parquet_file = tmp_path / "sample.parquet"
    parquet_file.touch()

    with pytest.raises(CapabilityError):
        make_sql_executor(parquet_file, dialect=SqlDialect.SQLITE)


def test_executor_compiled_attach_and_detach(tmp_path: Path):
    from defs.sql.compiler import QueryCompiler
    from defs.sql.statements import Attach, Detach

    # 1. Create a secondary SQLite file
    sub_file = tmp_path / "sub.db"
    scon = sqlite3.connect(sub_file)
    scon.execute("CREATE TABLE chunk_docs (id TEXT, val TEXT)")
    scon.execute("INSERT INTO chunk_docs VALUES ('c1', 'data from attached db')")
    scon.commit()
    scon.close()

    # 2. Test execution via SQLite executor
    sqlite_exec = make_sql_executor(":memory:", dialect=SqlDialect.SQLITE)
    sqlite_comp = QueryCompiler("sqlite")
    sqlite_exec.exec(sqlite_comp.compile(Attach(path=str(sub_file), alias="sub_db")))
    rows = sqlite_exec.query(
        sqlite_statement("SELECT id, val FROM sub_db.chunk_docs WHERE id = ?", "c1")
    )
    assert rows == [{"id": "c1", "val": "data from attached db"}]
    sqlite_exec.exec(sqlite_comp.compile(Detach(alias="sub_db")))
    sqlite_exec.close()

    # 3. Test execution via DuckDB executor
    duck_exec = make_sql_executor(dialect=SqlDialect.DUCKDB)
    duck_comp = QueryCompiler("duckdb")
    duck_exec.exec(
        duck_comp.compile(
            Attach(path=str(sub_file), alias="sub_db", read_only=True, db_type="sqlite")
        )
    )
    rows = duck_exec.query(
        duckdb_statement("SELECT id, val FROM sub_db.chunk_docs WHERE id = ?", "c1")
    )
    assert rows == [{"id": "c1", "val": "data from attached db"}]
    duck_exec.exec(duck_comp.compile(Detach(alias="sub_db")))
    duck_exec.close()


def test_executor_rejects_uncompiled_or_wrong_dialect_statements():
    executor = SqlExecutor(
        DbApiBackend(sqlite3.connect(":memory:"), dialect=SqlDialect.SQLITE)
    )
    with pytest.raises(TypeError):
        executor.exec("CREATE TABLE records (cik TEXT)")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        executor.exec(CompiledQuery("SELECT 1", (), SqlDialect.DUCKDB))
    executor.close()
