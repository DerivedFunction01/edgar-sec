"""Tests for SQLite DocumentCache storage, selective clearing, and export."""

from __future__ import annotations

import hashlib
import sqlite3
import zipfile
from pathlib import Path

import pytest
import zstandard

from edgar_sec.apps.client.cache import DocumentCache


def test_document_cache_put_get_and_count(tmp_path: Path) -> None:
    db_file = tmp_path / "cache.sqlite"
    cache = DocumentCache(db_path=db_file)

    payload = b"<html>10-K Content</html>"
    cache.put(
        accession="0000320193-23-000106",
        cik=320193,
        form="10-K",
        filename="aapl-20230930.htm",
        content=payload,
    )

    retrieved = cache.get("0000320193-23-000106", "aapl-20230930.htm")
    assert retrieved == payload
    assert cache.count() == 1
    assert cache.count(accession="0000320193-23-000106") == 1
    assert cache.count(cik=320193) == 1
    assert cache.count(cik=999999) == 0


def test_document_cache_has_reports_presence(tmp_path: Path) -> None:
    cache = DocumentCache(db_path=tmp_path / "cache.sqlite")
    assert not cache.has("acc-1", "doc1.txt")
    cache.put("acc-1", 100, "10-K", "doc1.txt", b"doc 1")
    assert cache.has("acc-1", "doc1.txt")
    assert not cache.has("acc-1", "doc2.txt")
    assert not cache.has("acc-2", "doc1.txt")
    cache.clear(accession="acc-1")
    assert not cache.has("acc-1", "doc1.txt")


def test_document_cache_selective_clear(tmp_path: Path) -> None:
    db_file = tmp_path / "cache.sqlite"
    cache = DocumentCache(db_path=db_file)

    cache.put("acc-1", 100, "10-K", "doc1.txt", b"doc 1")
    cache.put("acc-2", 100, "10-Q", "doc2.txt", b"doc 2")
    cache.put("acc-3", 200, "8-K", "doc3.txt", b"doc 3")
    assert cache.count() == 3

    deleted_acc = cache.clear(accession="acc-1")
    assert deleted_acc == 1
    assert cache.count() == 2

    deleted_cik = cache.clear(cik=100)
    assert deleted_cik == 1
    assert cache.count() == 1

    deleted_all = cache.clear()
    assert deleted_all == 1
    assert cache.count() == 0


def test_document_cache_export_files_and_zip(tmp_path: Path) -> None:
    db_file = tmp_path / "cache.sqlite"
    cache = DocumentCache(db_path=db_file)

    cache.put("acc-1", 100, "10-K", "doc1.txt", b"doc 1 content")
    cache.put("acc-2", 200, "10-Q", "doc2.txt", b"doc 2 content")

    export_dir = tmp_path / "exported"
    written = cache.export_files(export_dir, accession="acc-1")
    assert len(written) == 1
    assert written[0].read_bytes() == b"doc 1 content"

    zip_file = tmp_path / "archive.zip"
    cache.export_zip(zip_file)
    assert zip_file.is_file()

    with zipfile.ZipFile(zip_file, "r") as zf:
        names = zf.namelist()
        assert "acc-1/doc1.txt" in names
        assert "acc-2/doc2.txt" in names
        assert zf.read("acc-1/doc1.txt") == b"doc 1 content"


def _html_body() -> bytes:
    rows = "".join(
        f"<tr><td>Revenue</td><td>{i}</td><td>{i * 7}</td></tr>" for i in range(400)
    )
    return (
        "<html><head><title>10-K</title></head><body><table>"
        + rows
        + "</table></body></html>"
    ).encode()


def test_document_cache_stores_zstd_payload(tmp_path: Path) -> None:
    db_file = tmp_path / "cache.sqlite"
    cache = DocumentCache(db_path=db_file)

    body = _html_body()
    cache.put("acc-1", 100, "10-K", "doc1.htm", body, content_type="text/html")

    conn = sqlite3.connect(str(db_file))
    try:
        codec, stored, byte_size = conn.execute(
            "SELECT storage_codec, content, byte_size FROM cached_documents "
            "WHERE accession = 'acc-1' AND filename = 'doc1.htm'"
        ).fetchone()
    finally:
        conn.close()
    assert codec == "zstd"
    assert stored != body
    assert len(stored) < len(body) // 2
    assert byte_size == len(body)
    assert cache.get("acc-1", "doc1.htm") == body


def test_document_cache_reads_pre_change_raw_row(tmp_path: Path) -> None:
    db_file = tmp_path / "cache.sqlite"
    payload = b"<html>earlier 10-K content</html>"
    conn = sqlite3.connect(str(db_file))
    try:
        conn.execute(
            """
            CREATE TABLE cached_documents (
                accession TEXT NOT NULL,
                cik INTEGER NOT NULL,
                form TEXT NOT NULL,
                filename TEXT NOT NULL,
                content_type TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                byte_size INTEGER NOT NULL,
                content BLOB NOT NULL,
                cached_at TEXT NOT NULL,
                PRIMARY KEY (accession, filename)
            )
            """
        )
        conn.execute(
            "INSERT INTO cached_documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "acc-earlier",
                100,
                "10-K",
                "earlier.htm",
                "text/html",
                hashlib.sha256(payload).hexdigest(),
                len(payload),
                payload,
                "2026-01-01T00:00:00Z",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    cache = DocumentCache(db_path=db_file)
    assert cache.get("acc-earlier", "earlier.htm") == payload

    cache.put("acc-earlier", 100, "10-K", "new.htm", _html_body())
    assert cache.get("acc-earlier", "new.htm") == _html_body()
    assert cache.get("acc-earlier", "earlier.htm") == payload


def test_document_cache_corrupt_zstd_payload_raises(tmp_path: Path) -> None:
    db_file = tmp_path / "cache.sqlite"
    cache = DocumentCache(db_path=db_file)
    cache.put("acc-1", 100, "10-K", "doc1.htm", _html_body())

    conn = sqlite3.connect(str(db_file))
    try:
        conn.execute(
            "UPDATE cached_documents SET content = ? "
            "WHERE accession = 'acc-1' AND filename = 'doc1.htm'",
            (b"this is not a zstd frame",),
        )
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(zstandard.ZstdError):
        cache.get("acc-1", "doc1.htm")
