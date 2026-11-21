"""Feed client factory for feeds ledger commands."""

from __future__ import annotations

from edgar_sec.engine.feeds.client import FeedClient
from edgar_sec.foundation.runtime.settings import resolve_runtime_settings
from edgar_sec.infra.sec_http.client import SecHttpClient


def build_http_client() -> SecHttpClient:
    """Build the SEC HTTP client from runtime settings."""
    runtime = resolve_runtime_settings()
    return SecHttpClient.from_settings(
        runtime.sec, cache_dir=runtime.cache_root, ttl_s=runtime.ttl_s
    )


def build_feed_client(http_client: SecHttpClient | None = None) -> FeedClient:
    """Build the shared feed core over an HTTP client."""
    return FeedClient(http_client or build_http_client())


__all__ = ["build_feed_client", "build_http_client"]
