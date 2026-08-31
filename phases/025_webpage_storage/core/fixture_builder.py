"""Populate an offline SQLite fixture from a target plan and live SEC client."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from defs.runtime.paths import resolve_paths
from defs.runtime.resources import derive_resources
from defs.sec_http import SecHttpClient, make_sec_http_client

from .chunk_worker import process_chunk
from .fetcher import LiveSecArchiveFetcher
from .pipeline import load_targets


def _build_default_http_client(workers: int) -> SecHttpClient:
    """Build the shared production SEC client.

    One client is shared by all fixture fetch threads so that pacing, cache,
    failure ledger, and metrics are aggregated through a single rate limiter
    instead of one independent limiter per thread.
    """
    return make_sec_http_client(max_concurrency=max(4, workers))


def fill_fixture(
    plan_dir: str | Path,
    fixture_id: str | None = None,
    *,
    limit: int | None = None,
    http_client: SecHttpClient | None = None,
    workers: int | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Fetch raw documents from live SEC and store directly in a SQLite fixture database.

    Fetches are spread across ``workers`` threads, but the fixture database
    remains a single SQLite writer owned by the coordinator. One shared
    ``SecHttpClient`` keeps all live requests under one aggregate rate
    limiter. ``workers`` defaults to the machine-local runtime thread count.
    """
    if workers is None:
        workers = derive_resources().threads
    if workers < 1:
        raise ValueError("workers must be positive")

    resolved_id = fixture_id or f"fix-{Path(plan_dir).name[:8]}"
    fixture_db = resolve_paths().fixture(resolved_id, dialect="sqlite").db_path
    fixture_db.parent.mkdir(parents=True, exist_ok=True)

    locators, _, _ = load_targets(plan_dir)
    if limit is not None and limit > 0:
        locators = locators[:limit]

    client = http_client or _build_default_http_client(workers)
    fetcher = LiveSecArchiveFetcher(client)

    chunk_result = process_chunk(
        chunk_id=f"fixture-{fixture_id}",
        worker_id="fixture-builder",
        locators=locators,
        occurrences=(),
        fetcher=fetcher,
        output_path=fixture_db,
        progress=progress,
        fetch_workers=workers,
    )

    return {
        "fixture_id": fixture_id,
        "database": str(fixture_db),
        "target_locators": chunk_result.locator_count,
        "total_persisted": chunk_result.blob_count,
        "newly_fetched": chunk_result.fetched_count,
        "failed_count": len(chunk_result.failures),
    }


__all__ = ["fill_fixture"]
