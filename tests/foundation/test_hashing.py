"""Unit tests for foundation.hashing."""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.hashing import file_sha256, sha256_bytes
from edgar_sec.infra.storage.duckdb import connect

HELLO_SHA256 = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"

# Catalog identity strings crossing the SQL/Python boundary. The filing
# catalog derives occurrence and locator keys inside DuckDB while oracle
# expectations are computed in Python, so the two must agree byte for byte.
CROSS_BOUNDARY_DIGESTS = [
    "",
    "hello world",
    "0000320193:000032019323000106:aapl-20230930.htm",
    "000032019323000106:0000320193-24-000077.txt",
    "00019617:000001961724000040:jpm-20231231.htm",
    "unicode:café",
]


def test_file_sha256_matches_known_digest(tmp_path: Path) -> None:
    path = tmp_path / "hello.txt"
    path.write_text("hello world", encoding="utf-8")
    assert file_sha256(path) == HELLO_SHA256


def test_sha256_bytes_agrees_with_file_sha256(tmp_path: Path) -> None:
    path = tmp_path / "hello.txt"
    path.write_text("hello world", encoding="utf-8")
    assert sha256_bytes(b"hello world") == file_sha256(path)


def test_file_sha256_streams_large_files(tmp_path: Path) -> None:
    path = tmp_path / "large.bin"
    payload = b"z" * (1024 * 1024 + 17)
    path.write_bytes(payload)
    assert file_sha256(path) == sha256_bytes(payload)


@pytest.mark.parametrize("text", CROSS_BOUNDARY_DIGESTS)
def test_duckdb_sha256_agrees_with_python(text: str) -> None:
    """Catalog IDs must be identical whether computed in SQL or in Python."""
    with connect() as con:
        duckdb_digest = con.execute("SELECT sha256(?)", [text]).fetchone()[0]
    assert duckdb_digest == sha256_bytes(text.encode("utf-8"))
