"""Contract tests for the read-only HTTP cache reader.

The reader must observe what ``SqlCache`` wrote, never create or modify
files, and fail open — report a miss — on missing, empty, corrupt, or
schema-drifted databases so callers degrade to the network path instead of
erroring.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from pathlib import Path

from defs.sec_http.cache import SqlCache, SqlCacheReader, make_cache_reader

URL = "https://www.sec.gov/Archives/edgar/data/1/doc.htm"


def _put(cache: SqlCache, url: str = URL, payload: bytes = b"payload") -> None:
    cache.put(
        url,
        payload,
        hashlib.sha256(payload).hexdigest(),
        len(payload),
        "bytes",
    )


def test_reader_observes_writer_payload(tmp_path: Path) -> None:
    _put(SqlCache(tmp_path))

    assert SqlCacheReader(tmp_path).get(URL) == b"payload"


def test_reader_treats_expired_json_as_miss(tmp_path: Path) -> None:
    url = "https://data.sec.gov/submissions/CIK0000000001.json"
    cache = SqlCache(tmp_path)
    _put(cache, url)
    import sqlite3

    with sqlite3.connect(tmp_path / "responses.sqlite") as conn:
        conn.execute("UPDATE url_responses SET expires_at = '2000-01-01T00:00:00Z'")
        conn.commit()
    assert SqlCacheReader(tmp_path).get(url) is None


def test_reader_sees_commits_after_reader_creation(tmp_path: Path) -> None:
    reader = SqlCacheReader(tmp_path)
    assert reader.get(URL) is None

    _put(SqlCache(tmp_path))

    assert reader.get(URL) == b"payload"


def test_reader_missing_database_fails_open_without_creating_files(
    tmp_path: Path,
) -> None:
    reader = SqlCacheReader(tmp_path)

    assert reader.get(URL) is None
    assert list(tmp_path.iterdir()) == []


def test_reader_empty_database_fails_open(tmp_path: Path) -> None:
    (tmp_path / "responses.sqlite").touch()

    assert SqlCacheReader(tmp_path).get(URL) is None


def test_reader_corrupt_database_fails_open(tmp_path: Path) -> None:
    (tmp_path / "responses.sqlite").write_bytes(b"definitely not a sqlite database")

    assert SqlCacheReader(tmp_path).get(URL) is None


def test_reader_drifted_schema_fails_open(tmp_path: Path) -> None:
    conn = sqlite3.connect(str(tmp_path / "responses.sqlite"))
    conn.execute("CREATE TABLE url_responses (unrelated TEXT)")
    conn.commit()
    conn.close()

    assert SqlCacheReader(tmp_path).get(URL) is None


def test_reader_is_thread_safe(tmp_path: Path) -> None:
    cache = SqlCache(tmp_path)
    urls = [f"https://www.sec.gov/Archives/doc/{i}.htm" for i in range(8)]
    for i, url in enumerate(urls):
        _put(cache, url, f"payload-{i}".encode())

    reader = SqlCacheReader(tmp_path)
    errors: list[Exception] = []

    def worker(i: int) -> None:
        try:
            for _ in range(25):
                assert reader.get(urls[i]) == f"payload-{i}".encode()
        except Exception as exc:  # noqa: BLE001 - collected for assertion
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(len(urls))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert not errors


def test_reader_close_is_safe_without_connection(tmp_path: Path) -> None:
    reader = SqlCacheReader(tmp_path)
    reader.close()
    reader.close()

    assert reader.get(URL) is None


def test_make_cache_reader_requires_a_directory() -> None:
    assert make_cache_reader(None) is None
    assert make_cache_reader("") is None
    assert isinstance(make_cache_reader("/tmp/kilo/cache"), SqlCacheReader)
