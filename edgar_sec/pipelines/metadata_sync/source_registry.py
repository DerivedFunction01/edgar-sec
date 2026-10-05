"""Immutable external SEC source snapshots.

Content-addressed from the payload digest: re-fetching unchanged content is a
no-op, and a hash mismatch against an existing snapshot is a conflict.
"""

from __future__ import annotations

import json
import tempfile
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from edgar_sec.foundation.hashing import file_sha256, sha256_bytes
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.atomic import atomic_write_bytes, atomic_write_json
from edgar_sec.infra.storage.duckdb import connect

from .paths import MetadataPaths

SOURCE_NAME = "company_tickers"
SOURCE_URL = "https://www.sec.gov/files/company_tickers.json"
SOURCE_UNIVERSE_NAME = "cik_lookup"
SOURCE_UNIVERSE_URL = "https://www.sec.gov/Archives/edgar/cik-lookup-data.txt"
SOURCE_SCHEMA_VERSION = "1.0.0"
SOURCE_MANIFEST_KIND = "metadata_source_snapshot"

__all__ = [
    "SOURCE_MANIFEST_KIND",
    "SOURCE_NAME",
    "SOURCE_SCHEMA_VERSION",
    "SOURCE_UNIVERSE_NAME",
    "SOURCE_UNIVERSE_URL",
    "SOURCE_URL",
    "SourceRegistryError",
    "SourceSnapshot",
    "load_source_snapshot",
    "parse_cik_lookup_universe",
    "parse_company_tickers",
    "refresh_cik_lookup_universe",
    "refresh_company_tickers",
    "resolve_universe_snapshot",
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
    """Parse a listing payload into rows; one malformed entry rejects the snapshot,
    because a partial listing silently shrinks the CIK universe.
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


def _source_suffix(source_url: str) -> str:
    """The payload's own filename suffix, so a text index is not mislabelled."""
    return Path(urlsplit(source_url).path).suffix or ".bin"


def _publish_source_snapshot(
    *,
    source_name: str,
    source_url: str,
    metadata_paths: MetadataPaths,
    client: Any,
    parse: Callable[..., tuple[Any, dict[str, int]]],
    mutable: bool = False,
) -> dict[str, Any]:
    """Fetch, content-address, and publish one immutable source snapshot."""
    raw_bytes = client.get_bytes(source_url, mutable=mutable)
    raw_sha256 = sha256_bytes(raw_bytes)
    snapshot_id = source_snapshot_id(raw_sha256)
    observed_at = _utc_now()
    _parsed, parse_report = parse(
        raw_bytes, snapshot_id=snapshot_id, observed_at=observed_at
    )

    raw_path = metadata_paths.source_snapshot_file(
        source_name, snapshot_id, suffix=_source_suffix(source_url)
    )
    manifest_path = metadata_paths.source_manifest_file(source_name, snapshot_id)
    if raw_path.exists() and file_sha256(raw_path) != raw_sha256:
        raise SourceRegistryError(f"immutable source snapshot conflict: {raw_path}")
    if not raw_path.exists():
        atomic_write_bytes(raw_path, raw_bytes)

    manifest = {
        "manifest_kind": SOURCE_MANIFEST_KIND,
        "manifest_schema_version": SOURCE_SCHEMA_VERSION,
        "source": source_name,
        "source_url": source_url,
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


_UNIVERSE_REPORT_QUERY = """
WITH parsed AS (
    SELECT
        regexp_extract(line, ':([0-9]{1,10}):$', 1) AS cik,
        rtrim(regexp_replace(line, ':[0-9]{1,10}:$', ''), ':') AS name,
        regexp_matches(line, '^(.*):[0-9]{1,10}:$') AS well_formed
    FROM read_csv(?, auto_detect=false, header=false, columns={'line':'VARCHAR'},
                  delim='\\x01', quote='', escape='', strict_mode=false)
)
SELECT
    count(*) AS line_count,
    count(DISTINCT cik) FILTER (WHERE well_formed) AS distinct_cik_count,
    count(*) FILTER (WHERE well_formed)
        - count(DISTINCT cik) FILTER (WHERE well_formed)
        AS collapsed_name_count,
    count(*) FILTER (WHERE NOT well_formed) AS malformed_line_count
FROM parsed
"""


def parse_cik_lookup_universe(
    raw_bytes: bytes, *, snapshot_id: str, observed_at: str
) -> tuple[None, dict[str, int]]:
    """Count the full registrant index without materializing it.

    A line that is not ``name:cik:`` rejects the snapshot: a partial index
    silently shrinks the universe.
    """
    staged_path: str
    with tempfile.NamedTemporaryFile(
        prefix="cik-lookup-", suffix=".txt", delete=False
    ) as staged:
        staged.write(raw_bytes)
        staged_path = staged.name
    try:
        con = connect()
        try:
            line_count, distinct_ciks, collapsed, malformed = con.execute(
                _UNIVERSE_REPORT_QUERY, [staged_path]
            ).fetchone()
        finally:
            con.close()
    finally:
        Path(staged_path).unlink(missing_ok=True)
    if int(malformed):
        raise SourceRegistryError(
            f"cik lookup index has {int(malformed)} malformed line(s); "
            "a partial index would silently shrink the universe"
        )
    return None, {
        "line_count": int(line_count),
        "distinct_cik_count": int(distinct_ciks),
        "collapsed_name_count": int(collapsed),
        "malformed_line_count": 0,
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
    return _publish_source_snapshot(
        source_name=SOURCE_NAME,
        source_url=SOURCE_URL,
        metadata_paths=metadata_paths,
        client=client,
        parse=parse_company_tickers,
    )


def refresh_cik_lookup_universe(
    *,
    metadata_paths: MetadataPaths,
    client: Any | None = None,
) -> dict[str, Any]:
    """Fetch and publish the immutable full-registrant index snapshot.

    The index is mutable despite its archive path, so it is cached with the shared TTL.
    """
    if client is None:
        from edgar_sec.foundation.runtime.settings import resolve_runtime_settings
        from edgar_sec.infra.sec_http.client import SecHttpClient

        settings = resolve_runtime_settings()
        client = SecHttpClient.from_settings(
            settings.sec, cache_dir=settings.cache_root, ttl_s=settings.ttl_s
        )
    return _publish_source_snapshot(
        source_name=SOURCE_UNIVERSE_NAME,
        source_url=SOURCE_UNIVERSE_URL,
        metadata_paths=metadata_paths,
        client=client,
        parse=parse_cik_lookup_universe,
        mutable=True,
    )


def resolve_universe_snapshot(metadata_paths: MetadataPaths) -> str:
    """The newest published universe snapshot id, or empty when none.

    It is recorded in the plan, so a later refresh cannot change what a plan means.
    """
    source_root = metadata_paths.sources_root / SOURCE_UNIVERSE_NAME
    if not source_root.is_dir():
        return ""
    newest: tuple[str, str] | None = None
    for snapshot_dir in source_root.iterdir():
        manifest_file = snapshot_dir / "manifest.json"
        if not snapshot_dir.is_dir() or not manifest_file.is_file():
            continue
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        snapshot_id = str(manifest.get("snapshot_id", ""))
        if not snapshot_id:
            continue
        candidate = (str(manifest.get("retrieved_at", "")), snapshot_id)
        if newest is None or candidate > newest:
            newest = candidate
    return newest[1] if newest is not None else ""


def load_source_snapshot(manifest_path: str | Path) -> SourceSnapshot:
    """Load a source manifest and verify the referenced payload digest."""
    path = Path(manifest_path)
    if not path.is_file():
        raise FileNotFoundError(f"source manifest not found: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("manifest_kind") != SOURCE_MANIFEST_KIND:
        raise SourceRegistryError("manifest is not a source snapshot manifest")
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
