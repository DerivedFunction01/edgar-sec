"""Immutable external SEC source snapshots.
Content-addressed from the payload digest: re-fetching unchanged content is a
no-op, and a hash mismatch against an existing snapshot is a conflict, not a
repair.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edgar_sec.foundation.hashing import file_sha256, sha256_bytes
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.atomic import atomic_write_bytes, atomic_write_json

from .paths import MetadataPaths

SOURCE_NAME = "company_tickers"
SOURCE_URL = "https://www.sec.gov/files/company_tickers.json"
SOURCE_SCHEMA_VERSION = "1.0.0"
SOURCE_MANIFEST_KIND = "metadata_source_snapshot"

__all__ = [
    "SOURCE_MANIFEST_KIND",
    "SOURCE_NAME",
    "SOURCE_SCHEMA_VERSION",
    "SOURCE_URL",
    "SourceRegistryError",
    "SourceSnapshot",
    "load_source_snapshot",
    "parse_company_tickers",
    "refresh_company_tickers",
    "source_snapshot_id",
]


class SourceRegistryError(ValueError):
    """Raised when a source snapshot cannot be parsed or validated."""


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    """A verified immutable source snapshot on disk."""

    manifest: dict[str, Any]
    raw_path: Path
    artifacts_root: Path


def source_snapshot_id(raw_sha256: str) -> str:
    """Content-addressed snapshot identifier for a source payload digest."""
    material = canonical_json([SOURCE_NAME, SOURCE_SCHEMA_VERSION, raw_sha256]).encode(
        "utf-8"
    )
    return sha256_bytes(material)[:32]


def _utc_now() -> str:
    from edgar_sec.pipelines.metadata_sync.planner import utc_now_iso

    return utc_now_iso()


def _normalise_listing(
    key: str, value: Any, snapshot_id: str, observed_at: str
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SourceRegistryError(f"source entry {key!r} must be an object")
    raw_cik = value.get("cik_str")
    if isinstance(raw_cik, bool) or raw_cik is None:
        raise SourceRegistryError(f"source entry {key!r} has no valid cik_str")
    text = str(raw_cik).strip()
    if not text.isdigit() or len(text) > 10:
        raise SourceRegistryError(f"source entry {key!r} has invalid cik_str")
    ticker = value.get("ticker", "")
    title = value.get("title", "")
    if not isinstance(ticker, str) or not isinstance(title, str):
        raise SourceRegistryError(f"source entry {key!r} has non-string listing fields")
    return {
        "source_key": str(key),
        "cik_padded": text.zfill(10),
        "ticker": ticker.strip(),
        "title": title.strip(),
        "source_snapshot_id": snapshot_id,
        "observed_at": observed_at,
    }


def parse_company_tickers(
    raw_bytes: bytes, *, snapshot_id: str, observed_at: str
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Parse a company ticker listing payload into normalized listing rows.
    One malformed entry rejects the snapshot; a partial listing silently shrinks
    the CIK universe.
    """
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceRegistryError(
            f"company ticker source is not valid JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise SourceRegistryError("company ticker source root must be an object")

    listings = [
        _normalise_listing(str(key), payload[key], snapshot_id, observed_at)
        for key in sorted(payload, key=str)
    ]
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
    *,
    metadata_paths: MetadataPaths,
    client: Any | None = None,
) -> dict[str, Any]:
    """Fetch and publish one immutable company ticker source snapshot."""
    if client is None:
        from edgar_sec.foundation.runtime.settings import resolve_runtime_settings
        from edgar_sec.infra.sec_http.client import SecHttpClient

        client = SecHttpClient.from_settings(resolve_runtime_settings().sec)

    raw_bytes = client.get_bytes(SOURCE_URL)
    raw_sha256 = sha256_bytes(raw_bytes)
    snapshot_id = source_snapshot_id(raw_sha256)
    observed_at = _utc_now()
    _listings, parse_report = parse_company_tickers(
        raw_bytes, snapshot_id=snapshot_id, observed_at=observed_at
    )

    raw_path = metadata_paths.source_snapshot_file(SOURCE_NAME, snapshot_id)
    manifest_path = metadata_paths.source_manifest_file(SOURCE_NAME, snapshot_id)
    if raw_path.exists() and file_sha256(raw_path) != raw_sha256:
        raise SourceRegistryError(f"immutable source snapshot conflict: {raw_path}")
    if not raw_path.exists():
        atomic_write_bytes(raw_path, raw_bytes)

    manifest = {
        "manifest_kind": SOURCE_MANIFEST_KIND,
        "manifest_schema_version": SOURCE_SCHEMA_VERSION,
        "source": SOURCE_NAME,
        "source_url": SOURCE_URL,
        "snapshot_id": snapshot_id,
        "retrieved_at": observed_at,
        "raw_path": str(raw_path),
        "raw_sha256": raw_sha256,
        "byte_count": len(raw_bytes),
        "parser_version": SOURCE_SCHEMA_VERSION,
        **parse_report,
        "validation_status": "ok",
    }
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        stable = (
            "manifest_kind",
            "snapshot_id",
            "raw_path",
            "raw_sha256",
            "byte_count",
        )
        if any(existing.get(key) != manifest.get(key) for key in stable):
            raise SourceRegistryError(
                f"immutable source manifest conflict: {manifest_path}"
            )
    else:
        atomic_write_json(manifest_path, manifest, canonical=False, indent=2)
    return manifest


def load_source_snapshot(manifest_path: str | Path) -> SourceSnapshot:
    """Load a source manifest and verify the referenced payload digest."""
    path = Path(manifest_path)
    if not path.is_file():
        raise FileNotFoundError(f"source manifest not found: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("manifest_kind") != SOURCE_MANIFEST_KIND:
        raise SourceRegistryError("manifest is not a company ticker source manifest")
    raw_path = Path(manifest["raw_path"])
    if not raw_path.is_file():
        raise FileNotFoundError(f"source snapshot payload not found: {raw_path}")
    if file_sha256(raw_path) != manifest.get("raw_sha256"):
        raise SourceRegistryError(
            "source snapshot payload hash does not match manifest"
        )
    return SourceSnapshot(
        manifest=manifest,
        raw_path=raw_path,
        artifacts_root=raw_path.parent,
    )
