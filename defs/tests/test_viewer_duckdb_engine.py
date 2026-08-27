"""Engine-level DuckDB guarantees the viewer relies on.

The DuckDB concurrency model gives us two distinct enforcement layers:

1. ``access_mode = 'READ_ONLY'`` (``duckdb.connect(path, read_only=True)``)
   makes the *engine* reject writes to a database file. This applies when a
   future artifact is itself a DuckDB database file — no keyword guard needed.
2. Read-only connections also never take writer file locks, so several viewer
   processes can read the same artifact simultaneously.

Our SQL console runs on a private ``:memory:`` connection reading Parquet/JSONL
via table functions; there is no database file for DuckDB to make read-only,
which is exactly why ``defs/viewer/sql_guard.py`` exists. These tests pin all
three behaviors.
"""

import duckdb
import pytest


@pytest.fixture()
def duckdb_artifact(tmp_path):
    path = tmp_path / "artifact.duckdb"
    writer = duckdb.connect(str(path))
    writer.execute("CREATE TABLE t (x INTEGER)")
    writer.execute("INSERT INTO t VALUES (1), (2)")
    writer.close()
    return path


def test_engine_read_only_blocks_writes(duckdb_artifact):
    reader = duckdb.connect(str(duckdb_artifact), read_only=True)

    assert reader.execute("SELECT SUM(x) FROM t").fetchone()[0] == 3

    for write in (
        "INSERT INTO t VALUES (3)",
        "CREATE TABLE t2 (x INTEGER)",
        "UPDATE t SET x = 9",
        "DELETE FROM t",
    ):
        with pytest.raises(duckdb.Error):
            reader.execute(write)

    # Nothing leaked past the engine: data is unchanged after all attempts.
    assert reader.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
    reader.close()


def test_copy_to_filesystem_is_not_blocked_by_read_only_mode(duckdb_artifact, tmp_path):
    """Engine read-only protects the database file only: COPY TO writes to the
    local filesystem and succeeds even on a read_only connection. The console
    keyword guard (which rejects COPY) is therefore required defense in depth,
    not redundancy."""
    out = tmp_path / "leak.parquet"
    reader = duckdb.connect(str(duckdb_artifact), read_only=True)
    try:
        reader.execute(f"COPY t TO '{out}' (FORMAT PARQUET)")
        assert out.exists()
    finally:
        reader.close()


def test_read_only_connections_read_concurrently(duckdb_artifact):
    first = duckdb.connect(str(duckdb_artifact), read_only=True)
    second = duckdb.connect(str(duckdb_artifact), read_only=True)
    try:
        assert first.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
        assert second.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
    finally:
        first.close()
        second.close()


def test_artifact_files_take_no_database_locks(tmp_path):
    """Parquet/JSONL artifacts are read via table functions, not as databases:
    two in-memory sessions can read the same file with no lock contention."""
    import pyarrow as pa
    import pyarrow.parquet as parquet

    artifact = tmp_path / "shared.parquet"
    parquet.write_table(pa.table({"x": [1, 2, 3]}), str(artifact))

    first = duckdb.connect(":memory:")
    second = duckdb.connect(":memory:")
    try:
        expression = f"read_parquet('{artifact}')"
        assert first.execute(f"SELECT COUNT(*) FROM {expression}").fetchone()[0] == 3
        assert second.execute(f"SELECT COUNT(*) FROM {expression}").fetchone()[0] == 3
    finally:
        first.close()
        second.close()


def test_in_memory_console_sessions_have_no_engine_read_only_mode():
    """``:memory:`` sessions get no access_mode enforcement — the SQL guard in
    ``defs/viewer/sql_guard.py`` is the enforcement layer for the console."""
    conn = duckdb.connect(":memory:")
    try:
        conn.execute("CREATE TABLE not_read_only (x INTEGER)")
        conn.execute("INSERT INTO not_read_only VALUES (1)")
        assert conn.execute("SELECT COUNT(*) FROM not_read_only").fetchone()[0] == 1
    finally:
        conn.close()
