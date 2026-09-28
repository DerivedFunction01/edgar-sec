"""Unit tests for infra.sec_http.rate_limit."""

from __future__ import annotations

from edgar_sec.infra.sec_http.rate_limit import RateLimiter


def test_rate_limiter_pacing() -> None:
    limiter = RateLimiter(min_interval_s=0.01)
    delay1 = limiter.acquire()
    assert delay1 == 0.0

    throttled_delay = limiter.signal_throttle()
    assert throttled_delay >= 0.015

    snap = limiter.snapshot()
    assert snap["current_interval_s"] > 0.01


def test_rate_limiter_rejects_non_positive_interval() -> None:
    try:
        RateLimiter(min_interval_s=0.0)
    except ValueError as exc:
        assert "must be positive" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")
