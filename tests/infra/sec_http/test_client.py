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
    """Padded and unpadded CIKs must resolve to the same document.

    Two definitions of this builder used to exist, one of which padded and one
    of which did not, so the same CIK produced two different URLs depending on
    the caller.
    """
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
