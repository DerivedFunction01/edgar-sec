"""Exception hierarchy for SEC HTTP transport failures."""

from __future__ import annotations


class PermanentHttpError(Exception):
    """Non-retryable failure (404, non-retryable 4xx, bad payload)."""

    def __init__(self, url: str, reason: str, status_code: int | None = None):
        self.url = url
        self.reason = reason
        self.status_code = status_code
        super().__init__(f"permanent error for {url}: {reason} (status={status_code})")


class RetryExhausted(Exception):
    """Retry budget exhausted for a transient failure."""

    def __init__(self, url: str, reason: str, status_code: int | None = None):
        self.url = url
        self.reason = reason
        self.status_code = status_code
        super().__init__(
            f"retries exhausted for {url}: {reason} (status={status_code})"
        )


class ResponseTooLargeError(PermanentHttpError):
    """Response exceeded the configured size limit."""


__all__ = [
    "PermanentHttpError",
    "ResponseTooLargeError",
    "RetryExhausted",
]
