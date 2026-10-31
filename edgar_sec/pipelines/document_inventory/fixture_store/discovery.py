"""Manifest-only discovery for index fixtures."""

from __future__ import annotations

import json
from pathlib import Path

from edgar_sec.foundation.runtime.fixtures import (
    FIXTURE_DATABASE_NAME,
    FIXTURE_MANIFEST_NAME,
    FixtureManifestEnvelope,
)


def discover_index_fixtures(root: Path | str) -> list[dict]:
    """List readable fixture manifests without opening SQLite stores."""
    fixture_root = Path(root)
    if not fixture_root.is_dir():
        return []
    discovered = []
    for directory in sorted(fixture_root.iterdir(), key=lambda path: path.name):
        manifest_path = directory / FIXTURE_MANIFEST_NAME
        if not directory.is_dir() or not manifest_path.is_file():
            continue
        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = FixtureManifestEnvelope.from_mapping(raw)
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if (
            manifest.fixture_kind != "document_inventory.index_pages"
            or manifest.fixture_id != directory.name
            or manifest.storage_format != "sqlite"
            or manifest.storage_path != FIXTURE_DATABASE_NAME
        ):
            continue
        details = manifest.details
        discovered.append(
            {
                "fixture_id": directory.name,
                "schema_version": details.get("store_schema_version"),
                "capture_state": details.get("capture_state", "unknown"),
                "page_count": details.get("page_count", 0),
                "accession_count": details.get("accession_count", 0),
                "membership_count": details.get("membership_count", 0),
                "contributions": details.get("contributions", []),
            }
        )
    return discovered
