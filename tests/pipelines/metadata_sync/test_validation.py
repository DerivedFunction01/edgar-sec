"""Unit tests for pipelines.metadata_sync.validation."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa

from edgar_sec.infra.storage.duckdb import connect
from edgar_sec.infra.storage.parquet import write_parquet_table
from edgar_sec.pipelines.metadata_sync.validation import find_duplicate_accessions

FILINGS_SCHEMA = pa.schema(
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


def _write_filings(path: Path, rows: list[tuple[str, list[str]]]) -> str:
    table = pa.Table.from_arrays(
        [
            pa.array([cik for cik, _ in rows]),
            pa.array(
                [
                    [{"accession_number": acc, "form": "10-K"} for acc in accs]
                    for _, accs in rows
                ]
            ),
        ],
        schema=FILINGS_SCHEMA,
    )
    write_parquet_table(table, path)
    return str(path)


def test_duplicate_accession_fan_out_is_reported(tmp_path: Path) -> None:
    """The same filing under two registrants is expected, so it is reported."""
    path = _write_filings(
        tmp_path / "fanout.parquet",
        [
            ("0000000001", ["0001-02-000003"]),
            ("0000000002", ["0001-02-000003"]),
        ],
    )
    con = connect()
    try:
        found = find_duplicate_accessions(con, [path])
    finally:
        con.close()
    assert found == ["0001-02-000003"]


def test_a_uniquely_listed_accession_is_not_reported(tmp_path: Path) -> None:
    path = _write_filings(
        tmp_path / "unique.parquet",
        [
            ("0000000001", ["0001-02-000003"]),
            ("0000000002", ["0001-02-000004"]),
        ],
    )
    con = connect()
    try:
        assert find_duplicate_accessions(con, [path]) == []
    finally:
        con.close()


def test_no_paths_reports_no_duplicates() -> None:
    con = connect()
    try:
        assert find_duplicate_accessions(con, []) == []
    finally:
        con.close()
