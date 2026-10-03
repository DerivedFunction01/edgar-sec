"""Unit tests for infra.storage.duckdb."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pytest

from edgar_sec.infra.storage.duckdb import (
    connect,
    find_duplicate_keys,
    find_null_keys,
    sql_identifier,
    sql_literal,
    sql_path_list,
)
from edgar_sec.infra.storage.parquet import (
    write_parquet_table,
)

SCHEMA = pa.schema([("cik", pa.string()), ("val", pa.int64())])


def _write(path: Path, ciks: list[str], values: list[int]) -> str:
    table = pa.Table.from_arrays([pa.array(ciks), pa.array(values)], schema=SCHEMA)
    write_parquet_table(table, path)
    return str(path)


def test_sql_literal_escapes_embedded_quotes() -> None:
    assert sql_literal("a'b") == "'a''b'"
    assert sql_literal("plain") == "'plain'"


def test_sql_literal_cannot_be_escaped_out_of() -> None:
    """A hostile path must not be able to close the literal and append SQL."""
    hostile = "x.parquet' ; DROP TABLE source; --"
    literal = sql_literal(hostile)
    assert literal.count("'") % 2 == 0
    assert literal.endswith("'")
    assert literal.startswith("'")


def test_sql_identifier_accepts_bare_and_dotted_names() -> None:
    assert sql_identifier("source") == "source"
    assert sql_identifier("alias.column") == "alias.column"


def test_sql_identifier_rejects_unsafe_names() -> None:
    for name in ("source; DROP TABLE source", "column) OR 1=1 --", "", "a.b-c"):
        with pytest.raises(ValueError, match="unsafe SQL identifier"):
            sql_identifier(name)


def test_sql_path_list_escapes_each_element() -> None:
    listed = sql_path_list(["data/it's.parquet", "data/plain.parquet"])
    assert listed == "['data/it''s.parquet', 'data/plain.parquet']"


def test_duplicate_and_null_key_detection(tmp_path: Path) -> None:
    first = _write(tmp_path / "chunk1.parquet", ["0000000001"], [1])
    second = _write(tmp_path / "chunk2.parquet", ["0000000002"], [2])
    con = connect()
    try:
        assert find_duplicate_keys(con, [first, second], key_column="cik") == []
        assert find_null_keys(con, [first, second], key_column="cik") == 0
    finally:
        con.close()


def test_duplicate_and_null_keys_are_reported(tmp_path: Path) -> None:
    first = _write(tmp_path / "chunk1.parquet", ["0000000001"], [1])
    second = _write(tmp_path / "chunk2.parquet", ["0000000001", "0000000002"], [2, 3])
    con = connect()
    try:
        assert find_duplicate_keys(con, [first, second], key_column="cik") == [
            "0000000001"
        ]
    finally:
        con.close()


def test_every_connection_carries_the_resource_budget() -> None:
    """The four settings are applied through the single connect() seam.

    AGENTS.md section 2 requires every DuckDB connection to set threads,
    memory_limit, temp_directory and preserve_insertion_order from the
    cgroup-aware resource profile. The structural guarantee is that
    ``duckdb.connect`` is reachable from exactly one place, so nothing can open
    an unconfigured connection; this test pins both halves of that.
    """
    from pathlib import Path as _Path

    import edgar_sec

    package_root = _Path(edgar_sec.__file__).parent
    offenders = sorted(
        f"edgar_sec/{p.relative_to(package_root)}"
        for p in package_root.rglob("*.py")
        if "__pycache__" not in p.parts
        and "duckdb.connect(" in p.read_text(encoding="utf-8", errors="ignore")
    )
    assert offenders == ["edgar_sec/infra/storage/duckdb.py"], offenders

    with connect() as con:
        threads = con.execute("SELECT current_setting('threads')").fetchone()[0]
        memory_limit = con.execute("SELECT current_setting('memory_limit')").fetchone()[
            0
        ]
        preserve = con.execute(
            "SELECT current_setting('preserve_insertion_order')"
        ).fetchone()[0]
        temp_dir = con.execute("SELECT current_setting('temp_directory')").fetchone()[0]

    assert int(threads) >= 1
    assert memory_limit, "memory_limit is unset"
    assert bool(preserve) is False, "preserve_insertion_order must be false"
    assert temp_dir, "temp_directory is unset"
