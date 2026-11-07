"""Submissions client factory for metadata sync commands."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.foundation.runtime.settings import resolve_runtime_settings
from edgar_sec.pipelines.metadata_sync.sec_client import (
    BulkSubmissionsArchive,
    BulkSubmissionsClient,
    SubmissionsClient,
)


def build_client() -> SubmissionsClient:
    """Build a submissions client from runtime settings."""
    runtime = resolve_runtime_settings()
    return SubmissionsClient(
        settings=runtime.sec,
        cache_dir=str(runtime.cache_root),
        ttl_s=runtime.ttl_s,
    )


def build_bulk_client(dest_dir: str | Path) -> BulkSubmissionsClient:
    """Download the submissions bulk ZIP once and build its client."""
    archive = BulkSubmissionsArchive.download(build_client().http, dest_dir)
    return BulkSubmissionsClient(archive)
