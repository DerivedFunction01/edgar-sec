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


def test_sql_cache_clear_by_url_and_cik(tmp_path: Path) -> None:
    cache = SqlCache(tmp_path, ttl_s=3600)
    try:
        url_sub = "https://data.sec.gov/submissions/CIK0000320193.json"
        url_doc = (
            "https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/aapl.htm"
        )
        url_other = "https://data.sec.gov/submissions/CIK0000789019.json"

        cache.put(url_sub, b"aapl sub", sha256="s1", byte_size=8, content_kind="json")
        cache.put(url_doc, b"aapl doc", sha256="d1", byte_size=8, content_kind="html")
        cache.put(url_other, b"msft sub", sha256="m1", byte_size=8, content_kind="json")

        assert cache.clear(url=url_other) == 1
        assert cache.get(url_other) is None
        assert cache.get(url_sub) == b"aapl sub"
        assert cache.get(url_doc) == b"aapl doc"

        assert cache.clear(cik="0000320193") == 2
        assert cache.get(url_sub) is None
        assert cache.get(url_doc) is None
    finally:
        cache.close()


def test_sql_cache_clear_does_not_clear_larger_cik_substring(tmp_path: Path) -> None:
    """Verify that clearing CIK=1 does not touch CIK=10 or CIK=100."""
    cache = SqlCache(tmp_path, ttl_s=3600)
    try:
        url_1_sub = "https://data.sec.gov/submissions/CIK0000000001.json"
        url_1_doc = (
            "https://www.sec.gov/Archives/edgar/data/1/000000000123000001/doc.htm"
        )

        url_10_sub = "https://data.sec.gov/submissions/CIK0000000010.json"
        url_10_doc = (
            "https://www.sec.gov/Archives/edgar/data/10/000000001023000001/doc.htm"
        )

        url_100_sub = "https://data.sec.gov/submissions/CIK0000000100.json"
        url_100_doc = (
            "https://www.sec.gov/Archives/edgar/data/100/000000010023000001/doc.htm"
        )

        cache.put(url_1_sub, b"c1", sha256="s1", byte_size=2, content_kind="json")
        cache.put(url_1_doc, b"d1", sha256="d1", byte_size=2, content_kind="html")
        cache.put(url_10_sub, b"c10", sha256="s10", byte_size=3, content_kind="json")
        cache.put(url_10_doc, b"d10", sha256="d10", byte_size=3, content_kind="html")
        cache.put(url_100_sub, b"c100", sha256="s100", byte_size=4, content_kind="json")
        cache.put(url_100_doc, b"d100", sha256="d100", byte_size=4, content_kind="html")

        # Clearing CIK 1 must ONLY delete CIK 1, not 10 or 100
        assert cache.clear(cik=1) == 2
        assert cache.get(url_1_sub) is None
        assert cache.get(url_1_doc) is None

        assert cache.get(url_10_sub) == b"c10"
        assert cache.get(url_10_doc) == b"d10"
        assert cache.get(url_100_sub) == b"c100"
        assert cache.get(url_100_doc) == b"d100"

        # Clearing CIK 10 must ONLY delete CIK 10, not 100
        assert cache.clear(cik=10) == 2
        assert cache.get(url_10_sub) is None
        assert cache.get(url_10_doc) is None
        assert cache.get(url_100_sub) == b"c100"
        assert cache.get(url_100_doc) == b"d100"
    finally:
        cache.close()


def test_sql_cache_clear_by_pattern_and_stats(tmp_path: Path) -> None:
    cache = SqlCache(tmp_path, ttl_s=3600)
    try:
        cache.put(
            "https://data.sec.gov/submissions/CIK0000000001.json",
            b"sub 1",
            sha256="a",
            byte_size=5,
            content_kind="json",
        )
        cache.put(
            "https://www.sec.gov/Archives/edgar/data/1/0001/doc.htm",
            b"doc 1",
            sha256="b",
            byte_size=5,
            content_kind="html",
        )

        stats = cache.stats()
        assert stats["responses_count"] == 2
        assert stats["total_bytes"] == 10

        assert cache.clear(url_pattern="%.htm%") == 1
        assert (
            cache.get("https://www.sec.gov/Archives/edgar/data/1/0001/doc.htm") is None
        )
        assert (
            cache.get("https://data.sec.gov/submissions/CIK0000000001.json") is not None
        )

        cache.vacuum()
        assert cache.clear() == 1
        assert cache.stats()["responses_count"] == 0
    finally:
        cache.close()
