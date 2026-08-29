"""Generic bounded HTTP transport.

Owns a :mod:`requests` session and a semaphore that bounds simultaneous
requests. The semaphore is acquired only around the actual network send, so a
cache hit that never reaches :meth:`BoundedTransport.raw_send` consumes no slot.
Callers own retry logic; each retry is one ``raw_send`` and therefore consumes
one slot per attempt. The slot is released on success, HTTP error, and exception
paths. The transport is provider-neutral: it imposes no rate-limit pacing and no
SEC-specific status classification.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import requests

from .policy import ConcurrencyPolicy


class BoundedTransport:
    """Bounded, provider-neutral request transport."""

    def __init__(
        self,
        policy: ConcurrencyPolicy | None = None,
        session_factory: Callable[[], Any] = requests.Session,
    ):
        self.policy = policy or ConcurrencyPolicy()
        self._session = session_factory()
        self._semaphore = threading.Semaphore(self.policy.max_concurrency)

    @property
    def max_concurrency(self) -> int:
        return self.policy.max_concurrency

    def raw_send(
        self,
        url: str,
        *,
        headers: dict | None = None,
        timeout_s: float | None = None,
    ) -> Any:
        """Perform one bounded GET, releasing the slot on every exit path.

        The semaphore is acquired before the network call and released in a
        ``finally`` block so retries, HTTP errors, and transport exceptions all
        free the slot for the next in-flight request.
        """
        self._semaphore.acquire()
        try:
            return self._session.get(url, headers=headers, timeout=timeout_s)
        finally:
            self._semaphore.release()


__all__ = ["BoundedTransport"]
