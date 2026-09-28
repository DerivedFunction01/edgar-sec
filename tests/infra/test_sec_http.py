"""Unit tests for infra.sec_http: rate limiter, retry policy, SQLite cache, and client."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.infra.sec_http.cache import SqlCache
from edgar_sec.infra.sec_http.client import SecHttpClient, default_headers
from edgar_sec.infra.sec_http.rate_limit import RateLimiter
from edgar_sec.infra.sec_http.retry import RetryPolicy


def test_rate_limiter_pacing() -> None:
    limiter = RateLimiter(min_interval_s=0.01)
    delay1 = limiter.acquire()
    assert delay1 == 0.0

    # Throttle signal increases delay
    throttled_delay = limiter.signal_throttle()
    assert throttled_delay >= 0.015

    snap = limiter.snapshot()
    assert snap["current_interval_s"] > 0.01


def test_retry_policy_classification() -> None:
    policy = RetryPolicy(max_retries=3)
    assert policy.classify(200) == "ok"
    assert policy.classify(429) == "throttle"
    assert policy.classify(500) == "retry"
    assert policy.classify(503) == "retry"
    assert policy.classify(404) == "permanent"
    assert policy.classify(400) == "permanent"

    delay = policy.delay(attempt=1)
    assert delay > 0.0


def test_sqlite_cache_and_failure_ledger(tmp_path: Path) -> None:
    cache = SqlCache(tmp_path, json_ttl_s=3600)
    test_url = "https://data.sec.gov/submissions/CIK0000000001.json"

    # Cache miss
    assert cache.get(test_url) is None

    # Cache put and get
    payload = b'{"cik":"1","name":"Test Corp"}'
    cache.put(
        test_url, payload, sha256="abc", byte_size=len(payload), content_kind="json"
    )
    assert cache.get(test_url) == payload

    # Failure ledger
    assert cache.load_failure_entry(test_url) is None
    fail_url = "https://data.sec.gov/submissions/CIK9999999999.json"
    cache.record_failure(
        fail_url, kind="not_found", detail="HTTP 404", status_code=404, permanent=True
    )

    entry = cache.load_failure_entry(fail_url)
    assert entry is not None
    assert entry["permanent"] is True
    assert entry["failed_runs"] == 1

    # Record failure again increments runs
    cache.record_failure(
        fail_url, kind="not_found", detail="HTTP 404", status_code=404, permanent=True
    )
    entry2 = cache.load_failure_entry(fail_url)
    assert entry2 is not None
    assert entry2["failed_runs"] == 2

    # Clear failure
    cache.clear_failure(fail_url)
    assert cache.load_failure_entry(fail_url) is None
    cache.close()


def test_sec_http_client_urls_and_cache_probe(tmp_path: Path) -> None:
    headers = default_headers("Sample Company test@sample.com")
    assert headers["User-Agent"] == "Sample Company test@sample.com"

    client = SecHttpClient(
        user_agent="Sample Company test@sample.com",
        cache_dir=tmp_path,
    )
    sub_url = client.submissions_url("320193")
    assert sub_url == "https://data.sec.gov/submissions/CIK0000320193.json"

    archive_url = client.archives_url(
        "320193", "0000320193-23-000106", "aapl-20230930.htm"
    )
    assert (
        archive_url
        == "https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/aapl-20230930.htm"
    )

    # Peek cache returns None for miss, bytes for hit
    assert client.peek_cache(sub_url) is None
    client._cache_put(sub_url, b'{"status":"ok"}', "hash", 15, "json")
    assert client.peek_cache(sub_url) == b'{"status":"ok"}'
    assert client.metrics.cache_hits == 1
