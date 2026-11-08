"""Feed-archives ingest: enumerate, store, inventory, and publish one range.

Payloads enter the bulk-archive store only; the sole published product is
the inventory relation. Nothing is acquired into the document store.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from edgar_sec.domain.sec_urls import feed_archive_url, feed_listing_url
from edgar_sec.foundation.runtime.settings import resolve_runtime_settings
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.infra.sec_http.streaming import StreamFailure
from edgar_sec.infra.storage.bulk_archive import ArchiveReference, BulkArchiveStore

from .feed_inventory import FeedUnit, inventory_tarball, parse_listing_units
from .feed_publish import publish_inventory, published_archive_shas
from .options import FeedIngestOptions, iter_days
from .paths import AcquisitionPaths

SOURCE_ID = "feed_archives"


@dataclass(frozen=True, slots=True)
class FeedIngestResult:
    """Outcome of one Feed-archives ingest over a stated range."""

    units_considered: int
    units_fetched: int
    units_from_store: int
    units_skipped: int
    bundles: int
    malformed_bundles: int
    published: bool
    snapshot_id: str | None
    new_rows: int
    total_rows: int


def build_http_client() -> SecHttpClient:
    """Build the SEC HTTP client from runtime settings."""
    runtime = resolve_runtime_settings()
    return SecHttpClient.from_settings(
        runtime.sec, cache_dir=runtime.cache_root, ttl_s=runtime.ttl_s
    )


def enumerate_units(
    options: FeedIngestOptions, *, http: SecHttpClient
) -> list[FeedUnit]:
    """Enumerate the range's tarball units from the Feed listings."""
    wanted = set(iter_days(options.start, options.end))
    quarters = sorted({(day.year, (day.month - 1) // 3 + 1) for day in wanted})
    units: list[FeedUnit] = []
    for year, quarter in quarters:
        listing = http.get_text(feed_listing_url(year, quarter))
        units.extend(
            unit for unit in parse_listing_units(listing) if unit.day in wanted
        )
    return sorted(units, key=lambda unit: (unit.day, unit.filename))


def ingest_feed_archives(
    options: FeedIngestOptions,
    *,
    http: SecHttpClient,
    now: datetime | None = None,
) -> FeedIngestResult:
    """Ingest every Feed unit in the options' range and publish inventory."""
    paths = options.acquisition_paths()
    fetched_at = now or datetime.now(UTC)
    store = BulkArchiveStore(paths.bulk_archives_root)
    stored = {
        reference.manifest.source_url: reference
        for reference in store.list_archives(SOURCE_ID)
    }
    published_shas = published_archive_shas(paths, options.branch)
    units = enumerate_units(options, http=http)

    records = []
    fetched = from_store = skipped = malformed = 0
    for unit in units:
        url = feed_archive_url(
            unit.day.year, (unit.day.month - 1) // 3 + 1, unit.filename
        )
        reference = stored.get(url)
        if reference is not None and reference.sha256 in published_shas:
            skipped += 1
            continue
        if reference is not None:
            from_store += 1
            bundle_inventory = inventory_tarball(
                reference.path, feed_date=unit.day, archive_sha256=reference.sha256
            )
        else:
            fetched += 1
            bundle_inventory = _fetch_and_inventory(paths, store, unit, url, http=http)
        records.extend(bundle_inventory.records)
        malformed += bundle_inventory.malformed_bundles

    publication = publish_inventory(
        paths, records, branch=options.branch, fetched_at=fetched_at
    )
    return FeedIngestResult(
        units_considered=len(units),
        units_fetched=fetched,
        units_from_store=from_store,
        units_skipped=skipped,
        bundles=len(records),
        malformed_bundles=malformed,
        published=publication.published,
        snapshot_id=publication.snapshot_id,
        new_rows=publication.new_rows,
        total_rows=publication.total_rows,
    )


def _fetch_and_inventory(
    paths: AcquisitionPaths,
    store: BulkArchiveStore,
    unit: FeedUnit,
    url: str,
    *,
    http: SecHttpClient,
):
    """Download one unit into the store and inventory it from staging."""
    runtime = resolve_runtime_settings()
    staging_dir = paths.feed_staging_root / "downloads"
    staging_dir.mkdir(parents=True, exist_ok=True)
    descriptor, staging_name = tempfile.mkstemp(
        prefix=f"feed-{unit.day.isoformat()}-", suffix=".tar.gz", dir=staging_dir
    )
    staging = Path(staging_name)
    try:
        os.close(descriptor)
        expected = urlsplit(url)

        def validate_redirect(redirect_url: str) -> None:
            parts = urlsplit(redirect_url)
            if (
                parts.scheme != "https"
                or parts.netloc != expected.netloc
                or parts.path != expected.path
            ):
                raise ValueError(f"feed redirect left the unit path: {redirect_url}")

        result = http.stream_to_file(
            url,
            staging,
            max_response_bytes=runtime.sec.bulk_archive_max_bytes,
            validate_redirect=validate_redirect,
        )
        if isinstance(result, StreamFailure):
            raise RuntimeError(f"feed download failed ({result.code}): {result.detail}")
        reference: ArchiveReference = store.put_file(SOURCE_ID, staging, source_url=url)
        return inventory_tarball(
            staging, feed_date=unit.day, archive_sha256=reference.sha256
        )
    finally:
        staging.unlink(missing_ok=True)


__all__ = [
    "SOURCE_ID",
    "FeedIngestResult",
    "build_http_client",
    "enumerate_units",
    "ingest_feed_archives",
]
