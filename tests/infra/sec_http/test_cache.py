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


def _expires_at_for(tmp_path: Path, url: str, **kwargs) -> str | None:
    """The stored expiry for a URL put into a fresh cache."""
    cache = SqlCache(tmp_path, ttl_s=3600)
    try:
        cache.put(
            url, b"payload", sha256="abc", byte_size=7, content_kind="text", **kwargs
        )
        con = cache._con
        row = con.execute(
            "SELECT expires_at FROM url_responses WHERE url = ?", (url,)
        ).fetchone()
        return row["expires_at"]
    finally:
        cache.close()


def test_a_non_json_url_never_expires_by_default(tmp_path: Path) -> None:
    """Archive documents are immutable once filed, so their cache entry is permanent."""
    assert (
        _expires_at_for(tmp_path, "https://www.sec.gov/Archives/edgar/x/y.txt") is None
    )


def test_a_mutable_url_expires_when_declared(tmp_path: Path) -> None:
    """A mutable index filed under an archive path still honours the TTL."""
    expiry = _expires_at_for(
        tmp_path, "https://www.sec.gov/Archives/edgar/cik-lookup-data.txt", mutable=True
    )
    assert expiry is not None


def test_a_json_url_expires_without_being_declared_mutable(tmp_path: Path) -> None:
    assert (
        _expires_at_for(tmp_path, "https://www.sec.gov/files/company_tickers.json")
        is not None
    )


def test_mutable_does_not_pin_an_expired_entry(tmp_path: Path) -> None:
    """mutable=True still expires once the TTL elapses; it is not 'forever'."""
    cache = SqlCache(tmp_path, ttl_s=0)
    try:
        cache.put(
            "https://www.sec.gov/Archives/edgar/cik-lookup-data.txt",
            b"payload",
            sha256="abc",
            byte_size=7,
            content_kind="text",
            mutable=True,
        )
        # ttl_s=0 disables the TTL, so the entry is pinned.
        assert (
            cache.get("https://www.sec.gov/Archives/edgar/cik-lookup-data.txt")
            == b"payload"
        )
    finally:
        cache.close()
