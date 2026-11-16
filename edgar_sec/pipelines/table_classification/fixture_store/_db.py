"""SQLite storage and manifest IO for product fixtures."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from edgar_sec.foundation.runtime.fixtures import (
    FixtureManifestEnvelope,
    FixturePaths,
)
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.atomic import atomic_write_text

from .models import STORE_VERSION, FixtureStoreError, PlanPin, ProductStamps

_CREATE = """
CREATE TABLE IF NOT EXISTS classification_cases (
    case_id TEXT PRIMARY KEY,
    accession TEXT NOT NULL,
    source_document TEXT NOT NULL,
    products_json TEXT NOT NULL,
    products_sha256 TEXT NOT NULL
)
"""


def now_iso() -> str:
    """The current UTC instant in the manifest timestamp shape."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fixture_paths(artifacts_root: Path | str, fixture_id: str) -> FixturePaths:
    """Resolve one fixture's shared foundation paths."""
    from edgar_sec.foundation.runtime.fixtures import fixture_paths as resolve

    from .models import DATASET

    return resolve(artifacts_root, DATASET, fixture_id)


def open_fixture(paths: FixturePaths, *, readonly: bool = False) -> sqlite3.Connection:
    """Open a fixture database, creating its schema when writable."""
    if readonly:
        uri = f"file:{paths.storage_path}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
    else:
        paths.root.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(paths.storage_path)
    if not readonly:
        connection.execute(_CREATE)
        connection.commit()
    return connection


def read_manifest(paths: FixturePaths) -> FixtureManifestEnvelope:
    """Read and validate one fixture's manifest envelope."""
    if not paths.manifest_path.is_file():
        raise FixtureStoreError(f"fixture manifest is missing: {paths.fixture_id}")
    try:
        payload = json.loads(paths.manifest_path.read_text(encoding="utf-8"))
        return FixtureManifestEnvelope.from_mapping(payload)
    except (ValueError, OSError) as error:
        raise FixtureStoreError(f"fixture manifest is invalid: {error}") from error


def manifest_details(
    envelope: FixtureManifestEnvelope,
) -> tuple[PlanPin, ProductStamps]:
    """Extract the plan pin and stamps a manifest carries."""
    details = envelope.details
    if int(details.get("store_version", 0)) != STORE_VERSION:
        raise FixtureStoreError(
            f"unsupported fixture store version: {details.get('store_version')!r}"
        )
    return (
        PlanPin.from_record(dict(details["plan_pin"])),
        ProductStamps.from_record(dict(details["stamps"])),
    )


def write_manifest(
    paths: FixturePaths,
    *,
    plan_pin: PlanPin,
    stamps: ProductStamps,
    case_count: int,
    created_at: str,
) -> None:
    """Persist a fixture manifest through the shared envelope."""
    envelope = FixtureManifestEnvelope(
        fixture_kind="table_classification_products",
        fixture_id=paths.fixture_id,
        storage_format="sqlite",
        storage_path=paths.storage_filename,
        created_at=created_at,
        updated_at=now_iso(),
        details={
            "store_version": STORE_VERSION,
            "plan_pin": plan_pin.as_record(),
            "stamps": stamps.as_record(),
            "case_count": case_count,
        },
    )
    atomic_write_text(paths.manifest_path, canonical_json(envelope.to_mapping()) + "\n")
