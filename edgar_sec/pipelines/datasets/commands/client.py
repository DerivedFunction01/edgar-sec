"""SEC HTTP client factory for datasets commands."""

from __future__ import annotations

from edgar_sec.infra.sec_http.client import SecHttpClient

from ..ingest import build_http_client


def build_client() -> SecHttpClient:
    """Build a datasets SEC client from runtime settings."""
    return build_http_client()


__all__ = ["build_client"]
