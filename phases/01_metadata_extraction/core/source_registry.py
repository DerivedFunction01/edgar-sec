"""SEC source snapshots and immutable source evidence."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from defs.sec_http import make_sec_http_client
from defs.storage import (
    atomic_write_bytes,
    atomic_write_json,
    canonical_json,
    file_sha256,
    pa,
    read_records,
)
from defs.storage.models import DatasetSpec

from .input_manifest import TargetRow

SOURCE_NAME = "company_tickers"
SOURCE_URL = "https://www.sec.gov/files/company_tickers.json"
SOURCE_SCHEMA_VERSION = "1.0.0"
REGISTRY_SCHEMA_VERSION = "1.0.0"
SOURCE_MANIFEST_KIND = "metadata_source_snapshot"

LISTING_SCHEMA = pa.schema(
    [
        ("source_key", pa.string()),
        ("cik_padded", pa.string()),
        ("ticker", pa.string()),
        ("title", pa.string()),
        ("source_snapshot_id", pa.string()),
        ("observed_at", pa.string()),
    ]
)
REGISTRY_SCHEMA = pa.schema(
    [
        ("cik_padded", pa.string()),
        ("canonical_name", pa.string()),
        ("curated_name", pa.string()),
        ("active_title", pa.string()),
        ("tickers", pa.list_(pa.string())),
        ("source_snapshot_ids", pa.list_(pa.string())),
        ("curated_membership", pa.bool_()),
        ("active_listing_membership", pa.bool_()),
        ("historical_retained", pa.bool_()),
        ("processing_eligible", pa.bool_()),
        ("activity_class", pa.string()),
        ("refresh_cadence", pa.string()),
    ]
)
WORKLIST_SCHEMA = pa.schema(
    [
        ("cik_padded", pa.string()),
        ("name", pa.string()),
        ("source_row", pa.int64()),
        ("work_reason", pa.string()),
        ("source_snapshot_id", pa.string()),
        ("base_metadata_manifest_id", pa.string()),
    ]
)
WORKLIST_SPEC = DatasetSpec(
    name="metadata_augmentation_worklist",
    schema_version=REGISTRY_SCHEMA_VERSION,
    key_field="cik_padded",
    arrow_schema=WORKLIST_SCHEMA,
)


class SourceRegistryError(ValueError):
    """Raised when a source snapshot cannot be validated."""


@dataclass(frozen=True)
class SourceSnapshot:
    manifest: dict[str, Any]
    raw_path: Path
    artifacts_root: Path


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _snapshot_id(raw_sha256: str) -> str:
    return hashlib.sha256(
        canonical_json(
            ["company-tickers-source-v1", SOURCE_SCHEMA_VERSION, raw_sha256]
        ).encode()
    ).hexdigest()[:32]


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _normalise_listing(
    key: str, value: Any, snapshot_id: str, observed_at: str
) -> dict:
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
) -> tuple[list[dict], dict]:
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


def _paths(root: Path, snapshot_id: str) -> tuple[Path, Path]:
    from .paths import resolve_metadata_paths

    metadata_paths = resolve_metadata_paths(env={"ARTIFACTS_ROOT": str(root)})
    return (
        metadata_paths.source_snapshot_path(SOURCE_NAME, snapshot_id),
        metadata_paths.source_manifest_path(SOURCE_NAME, snapshot_id),
    )


def refresh_company_tickers(
    *,
    artifacts_root: str | Path,
    user_agent: str,
    timeout_s: float = 30.0,
    max_retries: int = 3,
    rate_limit_rps: float = 5.0,
    cache_dir: str | Path | None = None,
    client: Any | None = None,
) -> dict:
    """Fetch and publish one immutable company ticker source snapshot."""
    root = Path(artifacts_root).resolve()
    if client is None:
        from defs.sec_http import RateLimiter, RetryPolicy

        client = make_sec_http_client(
            user_agent=user_agent,
            timeout_s=timeout_s,
            rate_limiter=RateLimiter(min_interval_s=1.0 / rate_limit_rps),
            retry_policy=RetryPolicy(max_retries=max_retries),
            cache_dir=cache_dir,
        )
    raw_bytes = client.get_bytes(SOURCE_URL)
    raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    snapshot_id = _snapshot_id(raw_sha256)
    observed_at = _utc_now()
    _listings, parse_report = parse_company_tickers(
        raw_bytes, snapshot_id=snapshot_id, observed_at=observed_at
    )
    raw_path, manifest_path = _paths(root, snapshot_id)
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
        "raw_path": _relative(raw_path, root),
        "raw_sha256": raw_sha256,
        "byte_count": len(raw_bytes),
        "parser_version": SOURCE_SCHEMA_VERSION,
        **parse_report,
        "validation_status": "ok",
        "manifest_path": _relative(manifest_path, root),
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
        atomic_write_json(manifest_path, manifest, indent=None)
    return manifest


def load_source_snapshot(
    manifest_path: str | Path, *, artifacts_root: str | Path | None = None
) -> SourceSnapshot:
    path = Path(manifest_path)
    if not path.is_file():
        raise FileNotFoundError(f"source manifest not found: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("manifest_kind") != SOURCE_MANIFEST_KIND:
        raise SourceRegistryError("manifest is not a company ticker source manifest")
    root = Path(artifacts_root or path.parents[4]).resolve()
    raw_path = root / manifest["raw_path"]
    if not raw_path.is_file():
        raise FileNotFoundError(f"source snapshot payload not found: {raw_path}")
    if file_sha256(raw_path) != manifest.get("raw_sha256"):
        raise SourceRegistryError(
            "source snapshot payload hash does not match manifest"
        )
    return SourceSnapshot(manifest=manifest, raw_path=raw_path, artifacts_root=root)


def load_worklist(path: str | Path) -> list[TargetRow]:
    records = read_records(path, "parquet", spec=WORKLIST_SPEC)
    return sorted(
        [
            TargetRow(
                cik_padded=record["cik_padded"],
                name=record["name"],
                source_row=int(record.get("source_row") or 0),
            )
            for record in records
        ],
        key=lambda row: row.cik_padded,
    )


__all__ = [
    "LISTING_SCHEMA",
    "REGISTRY_SCHEMA",
    "REGISTRY_SCHEMA_VERSION",
    "SOURCE_NAME",
    "SOURCE_SCHEMA_VERSION",
    "SOURCE_URL",
    "WORKLIST_SCHEMA",
    "SourceRegistryError",
    "SourceSnapshot",
    "load_source_snapshot",
    "load_worklist",
    "parse_company_tickers",
    "refresh_company_tickers",
]
