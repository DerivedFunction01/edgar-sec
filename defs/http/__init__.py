"""Generic, provider-neutral bounded HTTP transport.

This package owns the request-execution boundary that is shared across HTTP
clients (SEC, and future OpenRouter/LLM adapters). It bounds simultaneous
network operations with a shared semaphore and deliberately knows nothing
about provider pacing, status classification, caching, or failure ledgers — those
remain in each provider's adapter layer.
"""

from __future__ import annotations

from .policy import DEFAULT_MAX_CONCURRENCY, ConcurrencyPolicy
from .transport import BoundedTransport

__all__ = [
    "DEFAULT_MAX_CONCURRENCY",
    "BoundedTransport",
    "ConcurrencyPolicy",
]
