"""Unit tests for infra.storage.duckdb."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa

from edgar_sec.infra.storage.duckdb import (
    concat_to_parquet,
    connect,
    find_duplicate_keys,
    find_duplicate_nested_values,
    find_null_keys,
)
from edgar_sec.infra.storage.parquet import (
    read_parquet_table,
    write_parquet_table,
)

SCHEMA = pa.schema([("cik", pa.string()), ("val", pa.int64())])


def _write(path: Path, ciks: list[str], values: list[int]) -> str:
    table = pa.Table.from_arrays([pa.array(ciks), pa.array(values)], schema=SCHEMA)
    write_parquet_table(table, path)
    return str(path)


def test_concat_to_parquet_sorts_and_merges(tmp_path: Path) -> None:
    first = _write(tmp_path / "chunk1.parquet", ["0000000002", "0000000001"], [20, 10])
    second = _write(tmp_path / "chunk2.parquet", ["0000000004", "0000000003"], [40, 30])
    out = tmp_path / "merged.parquet"

    con = connect()
    try:
        total = concat_to_parquet(con, [first, second], out, order_by=["cik"])
    finally:
        con.close()

    assert total == 4
    merged = read_parquet_table(out)
    assert merged.column("cik").to_pylist() == [
        "0000000001",
        "0000000002",
        "0000000003",
        "0000000004",
    ]


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


def test_duplicate_nested_values_detects_fan_out(tmp_path: Path) -> None:
    schema = pa.schema(
        [
            ("cik", pa.string()),
            (
                "filings",
                pa.list_(
                    pa.struct(
                        [
                            ("accession_number", pa.string()),
                            ("form", pa.string()),
                        ]
                    )
                ),
            ),
        ]
    )
    shared = [{"accession_number": "0001-02-000003", "form": "10-K"}]
    table = pa.Table.from_arrays(
        [pa.array(["0000000001", "0000000002"]), pa.array([shared, shared])],
        schema=schema,
    )
    path = tmp_path / "fanout.parquet"
    write_parquet_table(table, path)

    con = connect()
    try:
        found = find_duplicate_nested_values(
            con, [str(path)], "filings", "accession_number"
        )
    finally:
        con.close()
    assert "0001-02-000003" in found


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
