"""Metadata adapters for shared SEC source cohorts."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.infra.storage.cohort.models import CohortRecord
from edgar_sec.infra.storage.cohort.paths import CohortPaths, resolve_cohort_paths
from edgar_sec.infra.storage.cohort.sources import (
    refresh_official_source,
    resolve_active_source,
)

from .paths import MetadataPaths

SOURCE_NAME = "company_tickers"
SOURCE_URL = "https://www.sec.gov/files/company_tickers.json"
SOURCE_UNIVERSE_NAME = "cik_lookup"
SOURCE_UNIVERSE_URL = "https://www.sec.gov/Archives/edgar/cik-lookup-data.txt"

__all__ = [
    "SOURCE_NAME",
    "SOURCE_URL",
    "SOURCE_UNIVERSE_NAME",
    "SOURCE_UNIVERSE_URL",
    "SourceRegistryError",
    "parse_company_tickers",
    "refresh_cik_lookup_universe",
    "refresh_company_tickers",
    "resolve_universe_snapshot",
]


class SourceRegistryError(ValueError):
    """A source cohort payload or its listing rows cannot be used."""


def parse_company_tickers(
    raw_bytes: bytes, *, snapshot_id: str, observed_at: str
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Parse the raw ticker source for curated-versus-official comparison."""
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceRegistryError(
            f"company ticker source is not valid JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise SourceRegistryError("company ticker source root must be an object")

    listings = []
    for key in sorted(payload, key=str):
        value = payload[key]
        if not isinstance(value, dict):
            raise SourceRegistryError(f"source entry {key!r} must be an object")
        raw_cik = value.get("cik_str")
        if isinstance(raw_cik, bool) or raw_cik is None:
            raise SourceRegistryError(f"source entry {key!r} has no valid cik_str")
        cik = str(raw_cik).strip()
        if not cik.isdigit() or len(cik) > 10:
            raise SourceRegistryError(f"source entry {key!r} has invalid cik_str")
        ticker = value.get("ticker", "")
        title = value.get("title", "")
        if not isinstance(ticker, str) or not isinstance(title, str):
            raise SourceRegistryError(
                f"source entry {key!r} has non-string listing fields"
            )
        listings.append(
            {
                "source_key": str(key),
                "cik_padded": cik.zfill(10),
                "ticker": ticker.strip(),
                "title": title.strip(),
                "source_snapshot_id": snapshot_id,
                "observed_at": observed_at,
            }
        )
    listings.sort(
        key=lambda row: (
            row["cik_padded"],
            row["ticker"],
            row["title"],
            row["source_key"],
        )
    )
    counts = Counter(
        (row["cik_padded"], row["ticker"], row["title"]) for row in listings
    )
    return listings, {
        "listing_row_count": len(listings),
        "unique_cik_count": len({row["cik_padded"] for row in listings}),
        "duplicate_listing_count": sum(
            count - 1 for count in counts.values() if count > 1
        ),
        "malformed_row_count": 0,
    }


def refresh_company_tickers(
    *, metadata_paths: MetadataPaths, client: Any | None = None
) -> dict[str, Any]:
    """Refresh the shared official ticker cohort and return its provenance."""
    client = client or _default_client()
    paths = resolve_cohort_paths(metadata_paths.artifacts_root)
    record = _refresh(SOURCE_NAME, client, paths)
    return _official_source_summary(record, paths)


def refresh_cik_lookup_universe(
    *, metadata_paths: MetadataPaths, client: Any | None = None
) -> dict[str, Any]:
    """Refresh the shared active registrant-universe cohort."""
    client = client or _default_client()
    paths = resolve_cohort_paths(metadata_paths.artifacts_root)
    record = _refresh(SOURCE_UNIVERSE_NAME, client, paths)
    return _official_source_summary(record, paths)


def _default_client() -> Any:
    from edgar_sec.foundation.runtime.settings import resolve_runtime_settings
    from edgar_sec.infra.sec_http.client import SecHttpClient

    settings = resolve_runtime_settings()
    return SecHttpClient.from_settings(
        settings.sec, cache_dir=settings.cache_root, ttl_s=settings.ttl_s
    )


def _refresh(source: str, client: Any, paths: CohortPaths) -> CohortRecord:
    try:
        return refresh_official_source(
            source, client=client, paths=paths, catalog=CohortCatalog(paths)
        )
    except ValueError as exc:
        raise SourceRegistryError(str(exc)) from exc


def _official_source_summary(
    record: CohortRecord, paths: CohortPaths
) -> dict[str, Any]:
    details = json.loads(record.origin_json)
    raw_path = paths.resolve_relative_path(str(details["raw_path"]))
    return {
        "cohort_id": record.cohort_id,
        "source": details["source_name"],
        "source_url": details["source_url"],
        "snapshot_id": details["source_snapshot_id"],
        "retrieved_at": details["retrieved_at"],
        "raw_path": str(raw_path),
        "raw_sha256": details["raw_sha256"],
        "dataset_sha256": record.dataset_sha256,
        "row_count": record.row_count,
        "unique_cik_count": record.distinct_cik_count,
        **{
            key: value
            for key, value in details.items()
            if key
            not in {
                "source_name",
                "source_url",
                "source_snapshot_id",
                "retrieved_at",
                "raw_path",
                "raw_sha256",
            }
        },
    }


def resolve_universe_snapshot(metadata_paths: MetadataPaths) -> str:
    """Return the active shared universe source identity, if one is published."""
    paths = resolve_cohort_paths(metadata_paths.artifacts_root)
    record = resolve_active_source(SOURCE_UNIVERSE_NAME, catalog=CohortCatalog(paths))
    if record is None:
        return ""
    details = json.loads(record.origin_json)
    return str(details.get("source_snapshot_id", record.cohort_id))
