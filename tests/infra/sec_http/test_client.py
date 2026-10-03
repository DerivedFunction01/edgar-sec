"""Unit tests for infra.sec_http.client: headers, URLs, cache probe, get_json_ex."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from edgar_sec.domain.sec_urls import archives_url, submissions_url
from edgar_sec.infra.sec_http.client import SecHttpClient, default_headers
from edgar_sec.infra.sec_http.errors import PermanentHttpError


def test_default_headers_carry_user_agent() -> None:
    headers = default_headers("Sample Company test@sample.com")
    assert headers["User-Agent"] == "Sample Company test@sample.com"
    assert headers["Accept-Encoding"] == "gzip, deflate"


def test_submissions_url_pads_short_ciks() -> None:
    """Padding must not decide which URL the same CIK gets."""
    assert submissions_url("320193") == (
        "https://data.sec.gov/submissions/CIK0000320193.json"
    )
    assert submissions_url("0000320193") == submissions_url("320193")
    assert submissions_url(320193) == submissions_url("320193")


def test_archives_url_unpads_cik_and_hyphens() -> None:
    assert archives_url("320193", "0000320193-23-000106", "aapl-20230930.htm") == (
        "https://www.sec.gov/Archives/edgar/data/320193/"
        "000032019323000106/aapl-20230930.htm"
    )
    assert archives_url(
        "0000320193", "0000320193-23-000106", "aapl-20230930.htm"
    ) == archives_url("320193", "000032019323000106", "aapl-20230930.htm")


def test_cache_probe_and_hit_metric(tmp_path: Path) -> None:
    client = SecHttpClient(
        user_agent="Sample Company test@sample.com",
        cache_dir=tmp_path,
    )
    sub_url = submissions_url("320193")
    assert client.peek_cache(sub_url) is None
    client._cache_put(sub_url, b'{"status":"ok"}', "hash", 15, "json")
    assert client.peek_cache(sub_url) == b'{"status":"ok"}'
    assert client.metrics.cache_hits == 1


class _Response:
    def __init__(self, status_code: int, content: bytes) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = {}


class _Session:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[str] = []

    def get(self, url: str, headers=None, timeout=None) -> _Response:
        self.calls.append(url)
        return _Response(200, json.dumps(self.payload).encode("utf-8"))


def _client(tmp_path: Path, session: _Session) -> SecHttpClient:
    from edgar_sec.infra.sec_http.rate_limit import RateLimiter
    from edgar_sec.infra.sec_http.retry import RetryPolicy

    return SecHttpClient(
        user_agent="Sample Company test@sample.com",
        rate_limiter=RateLimiter(min_interval_s=0.001),
        retry_policy=RetryPolicy(max_retries=1, backoff_base_s=0.001, jitter=0.0),
        timeout_s=1.0,
        session_factory=lambda: session,
    )


def test_get_json_ex_returns_provenance(tmp_path: Path) -> None:
    payload = {"cik": "1", "name": "Test Corp"}
    session = _Session(payload)
    client = _client(tmp_path, session)

    parsed, byte_count, sha256 = client.get_json_ex(
        "https://data.sec.gov/submissions/CIK0000000001.json"
    )
    assert parsed == payload
    assert byte_count == len(json.dumps(payload).encode("utf-8"))
    assert len(sha256) == 64


def test_get_json_ex_rejects_non_object_root(tmp_path: Path) -> None:
    session = _Session([1, 2, 3])
    client = _client(tmp_path, session)
    with pytest.raises(PermanentHttpError, match="expected JSON object"):
        client.get_json_ex("https://data.sec.gov/submissions/CIK0000000001.json")


class _BytesSession:
    """A session returning a fixed oversized body."""

    def __init__(self, content: bytes) -> None:
        self.content = content
        self.calls: list[str] = []

    def get(self, url: str, headers=None, timeout=None) -> _Response:
        self.calls.append(url)
        return _Response(200, self.content)


def _size_limited_client(
    tmp_path: Path, session: _BytesSession, limit: int
) -> SecHttpClient:
    from edgar_sec.infra.sec_http.rate_limit import RateLimiter
    from edgar_sec.infra.sec_http.retry import RetryPolicy

    return SecHttpClient(
        user_agent="Sample Company test@sample.com",
        cache_dir=tmp_path,
        max_response_bytes=limit,
        rate_limiter=RateLimiter(min_interval_s=0.001),
        retry_policy=RetryPolicy(max_retries=1, backoff_base_s=0.001, jitter=0.0),
        timeout_s=1.0,
        session_factory=lambda: session,
    )


def test_response_too_large_is_permanent(tmp_path: Path) -> None:
    """Retrying cannot make an oversized body smaller, so it is permanent."""
    from edgar_sec.infra.sec_http.errors import ResponseTooLargeError

    body = b"x" * 4096
    session = _BytesSession(body)
    client = _size_limited_client(tmp_path, session, limit=1024)

    with pytest.raises(ResponseTooLargeError, match="exceeded 1024 bytes"):
        client.get_bytes("https://www.sec.gov/files/company_tickers.json")

    assert len(session.calls) == 1
    assert client.peek_cache("https://www.sec.gov/files/company_tickers.json") is None


def test_response_too_large_is_recorded_as_a_permanent_failure(
    tmp_path: Path,
) -> None:
    from edgar_sec.infra.sec_http.errors import ResponseTooLargeError

    url = "https://www.sec.gov/files/company_tickers.json"
    session = _BytesSession(b"y" * 2048)
    client = _size_limited_client(tmp_path, session, limit=512)

    with pytest.raises(ResponseTooLargeError):
        client.get_bytes(url)

    # The ledger recorded it permanently, so the next attempt is skipped.
    with pytest.raises(PermanentHttpError, match="size_exceeded"):
        client.get_bytes(url)
    assert len(session.calls) == 1


def test_a_response_at_the_limit_is_accepted(tmp_path: Path) -> None:
    body = b"z" * 512
    session = _BytesSession(body)
    client = _size_limited_client(tmp_path, session, limit=512)
    assert client.get_bytes("https://www.sec.gov/files/company_tickers.json") == body


def test_the_size_guard_is_off_by_default(tmp_path: Path) -> None:
    body = b"w" * 10_000
    session = _BytesSession(body)
    client = _client(tmp_path, session)  # type: ignore[arg-type]
    assert client.max_response_bytes is None
    assert client.get_bytes("https://www.sec.gov/files/company_tickers.json") == body


# ------------------------------------------------- settings construction path
#
# Every fetching action builds its client from resolved settings, so a mistyped
# attribute name would disable all of them at once.


def test_from_settings_maps_every_declared_setting() -> None:
    """Sentinels, not defaults: a renamed attribute raises before any comparison."""
    from edgar_sec.foundation.runtime.settings.sec import SecSettings

    client = SecHttpClient.from_settings(
        SecSettings(
            user_agent="Sentinel Co sentinel@example.com",
            rate_limit_rps=2.0,
            timeout_s=11.5,
            max_retries=7,
            max_failure_attempts=5,
        )
    )
    assert client.user_agent == "Sentinel Co sentinel@example.com"
    assert client.timeout_s == 11.5
    assert client.rate_limiter.interval == pytest.approx(0.5)
    assert client.retry_policy.max_retries == 7
    assert client.max_failure_attempts == 5


def test_from_settings_accepts_the_resolved_registry() -> None:
    """The production path constructs from the registry, not a literal."""
    from edgar_sec.foundation.runtime.settings import resolve_runtime_settings

    settings = resolve_runtime_settings().sec
    client = SecHttpClient.from_settings(settings)
    assert client.user_agent == settings.user_agent
    assert client.timeout_s == settings.timeout_s
    assert client.retry_policy.max_retries == settings.max_retries
    assert client.rate_limiter.interval == pytest.approx(1.0 / settings.rate_limit_rps)


def test_from_settings_honors_its_optional_arguments(tmp_path: Path) -> None:
    from edgar_sec.foundation.runtime.settings.sec import SecSettings

    client = SecHttpClient.from_settings(
        SecSettings(), cache_dir=tmp_path, json_ttl_s=99
    )
    assert client.cache_dir == tmp_path.resolve()
    assert client.max_response_bytes is None
