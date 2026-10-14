"""Tests for SQLite DocumentCache storage, selective clearing, and export."""

from __future__ import annotations

import zipfile
from pathlib import Path

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
