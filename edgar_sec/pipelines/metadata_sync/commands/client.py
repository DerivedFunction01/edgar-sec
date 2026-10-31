"""Submissions client factory for metadata sync commands."""

from __future__ import annotations

from edgar_sec.foundation.runtime.settings import resolve_runtime_settings
from edgar_sec.pipelines.metadata_sync.sec_client import SubmissionsClient


def build_client() -> SubmissionsClient:
    """Build a submissions client from runtime settings."""
    runtime = resolve_runtime_settings()
    return SubmissionsClient(
        settings=runtime.sec,
        cache_dir=str(runtime.cache_root),
        ttl_s=runtime.ttl_s,
    )
