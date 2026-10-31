"""Offline tests for bounded SEC HTTP response streaming."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
import requests

from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.infra.sec_http.retry import RetryPolicy
from edgar_sec.infra.sec_http.rate_limit import RateLimiter
from edgar_sec.infra.sec_http.streaming import StreamFailure, StreamedResponse


class _Response:
    def __init__(
        self,
        status_code: int = 200,
        chunks: tuple[bytes, ...] = (),
        *,
        headers: dict[str, str] | None = None,
        url: str = "https://www.sec.gov/document.htm",
        error: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self.headers = headers or {}
        self.url = url
        self.chunks = chunks
        self.error = error
        self.closed = False
        self.requested_chunk_size: int | None = None

    def iter_content(self, chunk_size: int):
        self.requested_chunk_size = chunk_size
        yield from self.chunks
        if self.error:
            raise self.error

    def close(self) -> None:
        self.closed = True


class _Session:
    def __init__(self, *responses: _Response | Exception) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def mount(self, *_args: object) -> None:
        pass


def _client(tmp_path: Path, session: _Session) -> SecHttpClient:
    return SecHttpClient(
        user_agent="Sample Company test@sample.com",
        cache_dir=tmp_path / "cache",
        rate_limiter=RateLimiter(min_interval_s=0.001),
        retry_policy=RetryPolicy(max_retries=0),
        timeout_s=1,
        session_factory=lambda: session,
    )


def test_stream_writes_chunks_and_returns_digest_metadata(tmp_path: Path) -> None:
    url = "https://www.sec.gov/document.htm"
    body = b"first chunk" + b"second chunk"
    response = _Response(
        chunks=(b"first ", b"chunksecond ", b"chunk"),
        headers={"Content-Type": "text/html", "Content-Encoding": "gzip"},
    )
    session = _Session(response)
    client = _client(tmp_path, session)
    client._cache_put(url, b"cached body", "old", 11, "bytes")
    destination = tmp_path / "stage" / "document.bin"
    destination.parent.mkdir()

    result = client.stream_to_file(
        url,
        destination,
        max_response_bytes=len(body),
        validate_redirect=lambda _url: None,
    )

    assert isinstance(result, StreamedResponse)
    assert result.path == destination
    assert result.requested_url == url
    assert result.final_url == response.url
    assert result.byte_size == len(body)
    assert result.sha256 == hashlib.sha256(body).hexdigest()
    assert result.content_type == "text/html"
    assert result.content_encoding == "gzip"
    assert destination.read_bytes() == body
    assert not hasattr(result, "body")
    assert response.requested_chunk_size is not None
    assert response.closed
    assert session.calls[0][1]["stream"] is True
    assert session.calls[0][1]["allow_redirects"] is False
    assert client.peek_cache(url) == b"cached body"


def test_redirect_is_validated_before_following(tmp_path: Path) -> None:
    source = "https://www.sec.gov/start"
    final = "https://www.sec.gov/Archives/edgar/data/1/doc.htm"
    redirect = _Response(
        302,
        headers={"Location": "/Archives/edgar/data/1/doc.htm"},
        url=source,
    )
    response = _Response(chunks=(b"body",), url=final)
    session = _Session(redirect, response)
    client = _client(tmp_path, session)
    validated: list[str] = []

    result = client.stream_to_file(
        source,
        tmp_path / "destination",
        max_response_bytes=10,
        validate_redirect=validated.append,
    )

    assert isinstance(result, StreamedResponse)
    assert result.final_url == final
    assert validated == [final]
    assert [call[0] for call in session.calls] == [source, final]
    assert redirect.closed and response.closed


def test_refused_redirect_returns_failure_without_following(tmp_path: Path) -> None:
    source = "https://www.sec.gov/start"
    redirect = _Response(302, headers={"Location": "https://example.com/file"})
    session = _Session(redirect)
    client = _client(tmp_path, session)
    destination = tmp_path / "destination"

    result = client.stream_to_file(
        source,
        destination,
        max_response_bytes=100,
        validate_redirect=lambda _url: (_ for _ in ()).throw(ValueError("unsafe host")),
    )

    assert isinstance(result, StreamFailure)
    assert result.code == "unsafe_redirect"
    assert not result.retryable
    assert not destination.exists()
    assert len(session.calls) == 1
    assert redirect.closed


def test_404_has_a_distinct_nonretryable_failure(tmp_path: Path) -> None:
    url = "https://www.sec.gov/missing"
    response = _Response(404)
    client = _client(tmp_path, _Session(response))

    result = client.stream_to_file(
        url,
        tmp_path / "destination",
        max_response_bytes=100,
        validate_redirect=lambda _url: None,
    )

    assert isinstance(result, StreamFailure)
    assert result.code == "http_not_found"
    assert result.http_status == 404
    assert not result.retryable
    assert response.closed
    assert client.load_failure_entry(url)["last_kind"] == "not_found"  # type: ignore[index]


def test_retryable_http_status_uses_the_shared_retry_policy(tmp_path: Path) -> None:
    url = "https://www.sec.gov/document.htm"
    session = _Session(_Response(503), _Response(chunks=(b"recovered",)))
    client = _client(tmp_path, session)
    client.retry_policy = RetryPolicy(max_retries=1, backoff_base_s=0, jitter=0)

    result = client.stream_to_file(
        url,
        tmp_path / "destination",
        max_response_bytes=100,
        validate_redirect=lambda _url: None,
    )

    assert isinstance(result, StreamedResponse)
    assert result.byte_size == len(b"recovered")
    assert len(session.calls) == 2
    assert client.metrics.retries_used == 1
    assert client.load_failure_entry(url) is None


def test_decoded_chunks_are_enforced_and_partial_file_removed(tmp_path: Path) -> None:
    response = _Response(
        chunks=(b"decoded " * 5, b"overflow", b"not consumed"),
        headers={"Content-Length": "20", "Content-Encoding": "gzip"},
    )
    client = _client(tmp_path, _Session(response))
    destination = tmp_path / "destination"
    destination.write_bytes(b"previous file")

    result = client.stream_to_file(
        "https://www.sec.gov/document.htm",
        destination,
        max_response_bytes=40,
        validate_redirect=lambda _url: None,
    )

    assert isinstance(result, StreamFailure)
    assert result.code == "response_too_large"
    assert destination.read_bytes() == b"previous file"
    assert response.closed
    assert not list(tmp_path.glob(".sec-stream-*.tmp"))


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (requests.exceptions.Timeout("timed out"), "timeout"),
        (requests.exceptions.ConnectionError("offline"), "transport_error"),
    ],
)
def test_transfer_failures_remove_partial_file(
    tmp_path: Path, error: Exception, code: str
) -> None:
    response = _Response(chunks=(b"partial",), error=error)
    client = _client(tmp_path, _Session(response))
    destination = tmp_path / "destination"

    result = client.stream_to_file(
        "https://www.sec.gov/document.htm",
        destination,
        max_response_bytes=100,
        validate_redirect=lambda _url: None,
    )

    assert isinstance(result, StreamFailure)
    assert result.code == code
    assert result.retryable
    assert not destination.exists()
    assert response.closed
    assert not list(tmp_path.glob(".sec-stream-*.tmp"))


def test_empty_success_response_is_rejected(tmp_path: Path) -> None:
    response = _Response()
    client = _client(tmp_path, _Session(response))

    result = client.stream_to_file(
        "https://www.sec.gov/empty",
        tmp_path / "destination",
        max_response_bytes=100,
        validate_redirect=lambda _url: None,
    )

    assert isinstance(result, StreamFailure)
    assert result.code == "empty_body"
    assert response.closed
    assert not list(tmp_path.glob(".sec-stream-*.tmp"))


def test_stream_requires_a_finite_positive_size_limit(tmp_path: Path) -> None:
    client = _client(tmp_path, _Session())

    with pytest.raises(ValueError, match="positive finite integer"):
        client.stream_to_file(
            "https://www.sec.gov/document.htm",
            tmp_path / "destination",
            max_response_bytes=0,
            validate_redirect=lambda _url: None,
        )
