import threading
import time

from conftest import imp

http = imp("defs.sec_http")

import pytest


class FakeResponse:
    def __init__(self, status_code=200, content=b"{}", headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}


class FakeSession:
    """Scripted responses; records send timestamps for pacing assertions."""

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[float] = []
        self.urls: list[str] = []
        self.lock = threading.Lock()

    def get(self, url, headers=None, timeout=None):
        with self.lock:
            self.calls.append(time.monotonic())
            self.urls.append(url)
        if not self.script:
            return FakeResponse(200)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make_client(script, **kwargs):
    kwargs.setdefault("rate_limiter", http.RateLimiter(min_interval_s=0.01))
    kwargs.setdefault(
        "retry_policy", http.RetryPolicy(max_retries=2, backoff_base_s=0.01, jitter=0.0)
    )
    kwargs.setdefault("timeout_s", 1.0)
    session = FakeSession(script)
    client = http.SecHttpClient(
        user_agent="TestClient/1.0 test@example.com",
        session_factory=lambda: session,
        **kwargs,
    )
    return client, session


def test_get_json_200():
    client, _session = make_client([FakeResponse(200, b'{"ok": true}')])
    assert client.get_json("https://x/y.json") == {"ok": True}


def test_404_is_permanent_and_never_retries():
    client, session = make_client([FakeResponse(404, b"nope")])
    with pytest.raises(http.PermanentHttpError):
        client.get_json("https://x/missing.json")
    assert len(session.calls) == 1


def test_4xx_other_is_permanent():
    client, session = make_client([FakeResponse(403, b"forbidden")])
    with pytest.raises(http.PermanentHttpError):
        client.get_json("https://x/deny.json")
    assert len(session.calls) == 1


def test_429_retries_then_succeeds_and_signals_throttle():
    client, session = make_client([FakeResponse(429), FakeResponse(200, b'{"ok": 1}')])
    assert client.get_json("https://x/y.json") == {"ok": 1}
    assert len(session.calls) == 2
    assert client.metrics.snapshot()["throttled_count"] == 1
    assert client.rate_limiter.interval > 0.01  # delay increased after throttling


def test_429_with_retry_after_is_respected():
    client, _session = make_client(
        [FakeResponse(429, headers={"Retry-After": "7"}), FakeResponse(200, b"{}")]
    )
    start = time.monotonic()
    client.get_json("https://x/y.json")
    waited = time.monotonic() - start
    assert waited >= 6.5
    snapshot = client.metrics.snapshot()
    assert snapshot["status_counts"].get("429") == 1


def test_500_and_503_retry_then_exhaust():
    script = [FakeResponse(500), FakeResponse(503), FakeResponse(500)]
    client, session = make_client(script)
    with pytest.raises(http.RetryExhausted):
        client.get_json("https://x/y.json")
    assert len(session.calls) == 3  # 1 initial + 2 retries


def test_timeout_and_connection_errors_are_retryable_not_throttle():
    import requests as requests_lib

    script = [
        requests_lib.exceptions.Timeout(),
        requests_lib.exceptions.ConnectionError(),
        FakeResponse(200, b"{}"),
    ]
    client, _session = make_client(script)
    assert client.get_json("https://x/y.json") == {}
    snapshot = client.metrics.snapshot()
    assert snapshot["network_errors"] == 2
    assert snapshot["throttled_count"] == 0
    assert (
        client.rate_limiter.interval == 0.01
    )  # network errors never raise the interval


def test_exhausted_timeout_raises_retry_exhausted():
    import requests as requests_lib

    script = [requests_lib.exceptions.Timeout()] * 3
    client, session = make_client(script)
    with pytest.raises(http.RetryExhausted):
        client.get_json("https://x/y.json")
    assert len(session.calls) == 3


def test_malformed_json_is_permanent():
    client, _session = make_client([FakeResponse(200, b"not json")])
    with pytest.raises(http.PermanentHttpError):
        client.get_json("https://x/y.json")


def test_get_text_decodes_utf8():
    client, _session = make_client([FakeResponse(200, "héllo".encode())])
    assert client.get_text("https://x/f.txt") == "héllo"


def test_pacing_occurs_once_per_request():
    # 5 requests; a pacing helper applied twice would double the gaps.
    script = [FakeResponse(200, b"{}")] * 5
    client, session = make_client(
        script, rate_limiter=http.RateLimiter(min_interval_s=0.03)
    )
    for _ in range(5):
        client.get_json("https://x/y.json")
    gaps = [
        session.calls[i + 1] - session.calls[i] for i in range(len(session.calls) - 1)
    ]
    assert all(gap >= 0.028 for gap in gaps), gaps
    assert client.metrics.snapshot()["requests_total"] == 5


def test_concurrent_acquisition_does_not_burst():
    script = [FakeResponse(200, b"{}")] * 8
    client, session = make_client(
        script, rate_limiter=http.RateLimiter(min_interval_s=0.05)
    )
    errors = []

    def worker():
        try:
            client.get_json("https://x/y.json")
        except Exception as exc:  # pragma: no cover # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    gaps = sorted(
        session.calls[i + 1] - session.calls[i] for i in range(len(session.calls) - 1)
    )
    # The two closest calls must still be at least one interval apart,
    # allowing a small scheduling tolerance around time.sleep wake-ups.
    assert gaps[0] >= 0.04, gaps


def test_cache_hit_avoids_http_and_metrics_count_it(tmp_path):
    cache_dir = tmp_path / "cache"
    client, session = make_client(
        [FakeResponse(200, b'{"cached": true}')], cache_dir=str(cache_dir)
    )
    assert client.get_json("https://x/y.json") == {"cached": True}
    assert client.get_json("https://x/y.json") == {"cached": True}
    assert len(session.calls) == 1
    assert client.metrics.snapshot()["cache_hits"] == 1


def test_response_too_large_is_permanent():
    client, _session = make_client(
        [FakeResponse(200, b"x" * 100)], max_response_bytes=10
    )
    with pytest.raises(http.ResponseTooLargeError):
        client.get_json("https://x/y.json")


def test_metrics_distinguish_throttle_from_network():
    import requests as requests_lib

    script = [
        requests_lib.exceptions.ConnectionError(),
        FakeResponse(429),
        FakeResponse(200, b"{}"),
    ]
    client, _session = make_client(script)
    client.get_json("https://x/y.json")
    snapshot = client.metrics.snapshot()
    assert snapshot["network_errors"] == 1
    assert snapshot["throttled_count"] == 1
    assert snapshot["requests_total"] == 3
    assert snapshot["last_error"]
