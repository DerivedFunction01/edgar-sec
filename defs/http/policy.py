"""Provider-neutral concurrency policy for HTTP transports.

``max_concurrency`` caps simultaneous network operations for a single provider
client. It is intentionally independent of request pacing (RPS), which remains a
separate provider-policy concern. Values below 1 are rejected; adapters that
want more headroom (for example LLM providers) raise it without inheriting any
SEC rate-limit or status-classification semantics.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_MAX_CONCURRENCY = 16


@dataclass(frozen=True)
class ConcurrencyPolicy:
    """Bounded in-flight request policy."""

    max_concurrency: int = DEFAULT_MAX_CONCURRENCY

    def __post_init__(self) -> None:
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")


__all__ = ["DEFAULT_MAX_CONCURRENCY", "ConcurrencyPolicy"]
