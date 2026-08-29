"""Contract tests for the SEC HTTP client adapter.

Verifies the SEC layer keeps its own concurrency cap (8), that request-start
pacing (RPS) is independent of the in-flight concurrency semaphore, and that
cache hits never acquire a transport slot.
"""

from __future__ import annotations

import threading
import time

import pytest

from defs.sec_http import (
    DEFAULT_SEC_MAX_CONCURRENCY,
    PermanentHttpError,
    RateLimiter,
    RetryExhausted,
    RetryPolicy,
    SecHttpClient,
)


class _FakeResponse:
    def __init__(self, status_code: int = 200, content: bytes = b"{}"):
        self.status_code = status_code
        self.content = content
        self.headers = {}


class _CountingSession:
    def __init__(self, responder):
        self.responder = responder
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def get(self, url, headers=None, timeout=None):
        with self._lock:
            self.calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.02)
        with self._lock:
            self.active -= 1
        return self.responder(url)


def test_sec_default_max_concurrency_is_eight():
    client = SecHttpClient(user_agent="App/1.0 a@b.com")
    assert DEFAULT_SEC_MAX_CONCURRENCY == 8
    assert client._transport.max_concurrency == 8


def test_sec_client_honors_explicit_concurrency_cap():
    client = SecHttpClient(user_agent="App/1.0 a@b.com", max_concurrency=4)
    assert client._transport.max_concurrency == 4


def test_sec_client_rejects_invalid_concurrency():
    with pytest.raises(ValueError, match="max_concurrency"):
        SecHttpClient(user_agent="App/1.0 a@b.com", max_concurrency=0)


def test_sec_concurrency_capped_at_eight_under_load():
    session = _CountingSession(lambda url: _FakeResponse(200, b"{}"))
    client = SecHttpClient(
        user_agent="App/1.0 a@b.com",
        session_factory=lambda: session,
        rate_limiter=RateLimiter(min_interval_s=1e-6),
        retry_policy=RetryPolicy(max_retries=0),
    )

    urls = [f"https://data.sec.gov/submissions/CIK{i:010d}.json" for i in range(24)]

    def worker(url: str) -> None:
        try:
            client.get_json(url)
        except (PermanentHttpError, RetryExhausted):
            pass

    threads = [threading.Thread(target=worker, args=(u,)) for u in urls]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert session.calls == 24
    # No more than the SEC cap of 8 requests are ever in flight simultaneously.
    assert session.max_active <= DEFAULT_SEC_MAX_CONCURRENCY


def test_sec_rate_limit_pacing_is_independent_of_concurrency():
    # Raising the concurrency cap must not change the configured request-start
    # pacing; the rate limiter still enforces its own interval.
    client = SecHttpClient(
        user_agent="App/1.0 a@b.com",
        rate_limiter=RateLimiter(min_interval_s=0.05),
        max_concurrency=64,
    )
    assert client._transport.max_concurrency == 64

    # The rate limiter returns the delay the caller must sleep; pacing is driven
    # by the limiter interval, completely independent of the concurrency cap. The
    # first call starts now (delay ~0); the second is paced by the 0.05s interval.
    first_delay = client.rate_limiter.acquire()
    second_delay = client.rate_limiter.acquire()
    assert 0.0 <= first_delay < 0.01
    assert second_delay >= 0.05 - 0.005


def test_sec_cache_hit_does_not_acquire_slot(tmp_path):
    session = _CountingSession(lambda url: _FakeResponse(200, b"{}"))
    client = SecHttpClient(
        user_agent="App/1.0 a@b.com",
        session_factory=lambda: session,
        cache_dir=str(tmp_path / "cache"),
        rate_limiter=RateLimiter(min_interval_s=1e-6),
        retry_policy=RetryPolicy(max_retries=0),
    )
    url = "https://data.sec.gov/submissions/CIK0000000001.json"
    client.get_json(url)  # cache miss -> one raw_send
    assert session.calls == 1

    # Intercept the transport: a cache hit must not invoke raw_send (no slot).
    raw_calls: list[str] = []
    client._transport.raw_send = lambda u, **kw: raw_calls.append(u)  # type: ignore[method-assign]

    client.get_json(url)
    assert raw_calls == []
    assert session.calls == 1  # unchanged


def test_get_bytes_returns_raw_payload_without_decoding():
    session = _CountingSession(lambda url: _FakeResponse(200, b"\xff\xfe<html>"))
    client = SecHttpClient(
        user_agent="App/1.0 a@b.com",
        session_factory=lambda: session,
        rate_limiter=RateLimiter(min_interval_s=1e-6),
        retry_policy=RetryPolicy(max_retries=0),
    )
    url = "https://www.sec.gov/Archives/edgar/data/1/0000000001-000001.txt"
    assert client.get_bytes(url) == b"\xff\xfe<html>"
    assert session.calls == 1


def test_get_bytes_failure_ledger_preflight_skips_request(tmp_path):
    url = "https://www.sec.gov/Archives/missing.htm"
    session = _CountingSession(lambda u: _FakeResponse(404, b"not found"))
    first = SecHttpClient(
        user_agent="App/1.0 a@b.com",
        session_factory=lambda: session,
        cache_dir=str(tmp_path / "cache"),
        rate_limiter=RateLimiter(min_interval_s=1e-6),
        retry_policy=RetryPolicy(max_retries=0),
    )
    with pytest.raises(PermanentHttpError):
        first.get_bytes(url)
    assert session.calls == 1

    # A later session sharing the cache dir skips the dead URL without any HTTP request.
    second = SecHttpClient(
        user_agent="App/1.0 a@b.com",
        session_factory=lambda: session,
        cache_dir=str(tmp_path / "cache"),
        rate_limiter=RateLimiter(min_interval_s=1e-6),
        retry_policy=RetryPolicy(max_retries=0),
    )
    with pytest.raises(PermanentHttpError):
        second.get_bytes(url)
    assert session.calls == 1  # unchanged: preflight skip, no request
