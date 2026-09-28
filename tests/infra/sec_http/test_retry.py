"""Unit tests for infra.sec_http.retry."""

from __future__ import annotations

from edgar_sec.infra.sec_http.retry import RetryPolicy


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


def test_retry_delay_honors_retry_after() -> None:
    policy = RetryPolicy(max_retries=3, backoff_base_s=1.0, jitter=0.0)
    assert policy.delay(attempt=0, retry_after_s=2.5) == 2.5


def test_retry_backoff_grows_exponentially() -> None:
    policy = RetryPolicy(
        max_retries=5, backoff_base_s=1.0, backoff_cap_s=30.0, jitter=0.0
    )
    assert policy.delay(attempt=0) == 1.0
    assert policy.delay(attempt=1) == 2.0
    assert policy.delay(attempt=2) == 4.0
    assert policy.delay(attempt=10) == 30.0
