"""Contract tests for the generic bounded HTTP transport."""

from __future__ import annotations

import threading
import time

import pytest

from defs.http import BoundedTransport, ConcurrencyPolicy


class _FakeSession:
    def __init__(self, latency: float = 0.03):
        self.latency = latency
        self.calls = 0
        self.active = 0
        self.max_active = 0
        self._lock = threading.Lock()

    def get(self, url, headers=None, timeout=None):
        with self._lock:
            self.calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(self.latency)
        with self._lock:
            self.active -= 1
        return f"resp:{url}"


def test_transport_caps_simultaneous_requests():
    policy = ConcurrencyPolicy(max_concurrency=3)
    session = _FakeSession()
    transport = BoundedTransport(policy, session_factory=lambda: session)

    threads = [
        threading.Thread(target=transport.raw_send, args=(f"u{i}",)) for i in range(9)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert session.max_active <= 3
    assert session.calls == 9


def test_transport_passes_headers_and_timeout():
    seen = {}

    class CapturingSession:
        def get(self, url, headers=None, timeout=None):
            seen["headers"] = headers
            seen["timeout"] = timeout
            return "ok"

    transport = BoundedTransport(session_factory=CapturingSession)
    transport.raw_send("https://example/u", headers={"X": "1"}, timeout_s=7.5)
    assert seen["headers"] == {"X": "1"}
    assert seen["timeout"] == 7.5


def test_transport_releases_slot_on_success_and_http_error():
    policy = ConcurrencyPolicy(max_concurrency=1)
    calls = {"n": 0}

    class FlakySession:
        def get(self, url, headers=None, timeout=None):
            calls["n"] += 1
            # Simulate an HTTP error response object (no exception). The slot
            # must still be released so the next call proceeds.
            return type("R", (), {"status_code": 500, "content": b""})()

    transport = BoundedTransport(policy, session_factory=FlakySession)
    for _ in range(3):
        transport.raw_send("u")
    # No deadlock: all three attempts acquired and released the single slot.
    assert calls["n"] == 3


def test_transport_releases_slot_on_exception():
    policy = ConcurrencyPolicy(max_concurrency=1)
    calls = {"n": 0}

    class FailingSession:
        def get(self, url, headers=None, timeout=None):
            calls["n"] += 1
            raise RuntimeError("boom")

    transport = BoundedTransport(policy, session_factory=FailingSession)
    for _ in range(3):
        with pytest.raises(RuntimeError):
            transport.raw_send("u")
    # Each failure released the slot; a further call still acquires it.
    with pytest.raises(RuntimeError):
        transport.raw_send("u")
    assert calls["n"] == 4


def test_concurrency_policy_rejects_zero_and_negative():
    with pytest.raises(ValueError, match="max_concurrency"):
        ConcurrencyPolicy(max_concurrency=0)
    with pytest.raises(ValueError, match="max_concurrency"):
        ConcurrencyPolicy(max_concurrency=-4)


def test_default_max_concurrency_is_sixteen():
    assert ConcurrencyPolicy().max_concurrency == 16
    assert BoundedTransport().max_concurrency == 16
