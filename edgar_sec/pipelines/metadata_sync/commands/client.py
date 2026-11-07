"""Submissions client factory for metadata sync commands."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.foundation.runtime.settings import resolve_runtime_settings
from edgar_sec.infra.storage.bulk_archive import BulkArchiveStore
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


def build_bulk_client(store_root: str | Path) -> BulkSubmissionsClient:
    """Download the submissions bulk ZIP into the store and build its client."""
    runtime = resolve_runtime_settings()
    store = BulkArchiveStore(store_root)
    archive = BulkSubmissionsArchive.download(
        build_client().http,
        store,
        max_bytes=runtime.sec.bulk_archive_max_bytes,
    )
    return BulkSubmissionsClient(archive)


def build_bulk_client_from_store(
    store_root: str | Path, source_id: str, sha256: str
) -> BulkSubmissionsClient:
    """Build a bulk client over a stored archive, never downloading.

    An archive plan binds one stored archive; absence is an operator error,
    not a reason to fetch a different night's file.
    """
    store = BulkArchiveStore(store_root)
    reference = store.open(source_id, sha256)
    if reference is None:
        raise ValueError(
            f"stored archive not found for source {source_id!r} at {sha256}"
        )
    return BulkSubmissionsClient(
        BulkSubmissionsArchive(reference.path, archive_sha256=reference.sha256)
    )
