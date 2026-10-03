"""Unit tests for infra.sec_http.cache: SQLite cache and failure ledger."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.infra.sec_http.cache import SqlCache

TEST_URL = "https://data.sec.gov/submissions/CIK0000000001.json"
FAIL_URL = "https://data.sec.gov/submissions/CIK9999999999.json"


def test_cache_miss_then_put_get(tmp_path: Path) -> None:
    cache = SqlCache(tmp_path, ttl_s=3600)
    try:
        assert cache.get(TEST_URL) is None

        payload = b'{"cik":"1","name":"Test Corp"}'
        cache.put(
            TEST_URL,
            payload,
            sha256="abc",
            byte_size=len(payload),
            content_kind="json",
        )
        assert cache.get(TEST_URL) == payload
    finally:
        cache.close()


def test_failure_ledger_records_and_clears(tmp_path: Path) -> None:
    cache = SqlCache(tmp_path, ttl_s=3600)
    try:
        assert cache.load_failure_entry(FAIL_URL) is None

        cache.record_failure(
            FAIL_URL,
            kind="not_found",
            detail="HTTP 404",
            status_code=404,
            permanent=True,
        )
        entry = cache.load_failure_entry(FAIL_URL)
        assert entry is not None
        assert entry["permanent"] is True
        assert entry["failed_runs"] == 1

        cache.record_failure(
            FAIL_URL,
            kind="not_found",
            detail="HTTP 404",
            status_code=404,
            permanent=True,
        )
        repeated = cache.load_failure_entry(FAIL_URL)
        assert repeated is not None
        assert repeated["failed_runs"] == 2

        cache.clear_failure(FAIL_URL)
        assert cache.load_failure_entry(FAIL_URL) is None
    finally:
        cache.close()
