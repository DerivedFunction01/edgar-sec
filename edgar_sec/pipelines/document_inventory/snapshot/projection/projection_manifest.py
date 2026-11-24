"""Projection run identity and run-manifest lifecycle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from edgar_sec.domain.document_inventory.schemas import ENTRY_SCHEMA_VERSION
from edgar_sec.engine.filing_summary.parser import ENUMERATOR_FINGERPRINT
from edgar_sec.engine.index_pages.parser import PARSER_FINGERPRINT
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.pipelines.document_inventory.paths import InventoryRunPaths
from edgar_sec.pipelines.document_inventory.run_state.run_manifest import (
    InventoryRunManifest,
    ManifestMismatchError,
    WORK_ORDER_VERSION,
    read_run_manifest,
    validate_run_manifest,
    write_run_manifest,
)
from edgar_sec.pipelines.document_inventory.snapshot.contracts.schema import (
    LOOKUP_LAYOUT_VERSION,
    SNAPSHOT_RELATION_VERSION,
)

__all__ = ["intent_id", "read_projection_manifest", "run_manifest"]


def read_projection_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ManifestMismatchError("projection manifest is unreadable") from exc
    if not isinstance(payload, dict):
        raise ManifestMismatchError("projection manifest must be an object")
    return payload


def intent_id(
    *,
    catalog_id: str,
    catalog_plan_id: str,
    base_snapshot_id: str | None,
    base_manifest_sha256: str | None,
    cohort_fingerprint: str,
    chunk_size: int,
    refresh_salt: str | None,
) -> str:
    return (
        "run-"
        + canonical_hash(
            {
                "intent_version": "inventory-run-intent-v1",
                "catalog_id": catalog_id,
                "catalog_plan_id": catalog_plan_id,
                "base_snapshot_id": base_snapshot_id,
                "base_manifest_sha256": base_manifest_sha256,
                "cohort_fingerprint": cohort_fingerprint,
                "parser_version": PARSER_FINGERPRINT,
                "enumerator_version": ENUMERATOR_FINGERPRINT,
                "snapshot_relation_version": SNAPSHOT_RELATION_VERSION,
                "entry_schema_version": ENTRY_SCHEMA_VERSION,
                "lookup_layout_version": LOOKUP_LAYOUT_VERSION,
                "work_order_version": WORK_ORDER_VERSION,
                "chunk_size": chunk_size,
                "refresh_salt": refresh_salt,
            }
        )[:28]
    )


def run_manifest(
    paths: InventoryRunPaths,
    *,
    base_snapshot_id: str | None,
    plan_id: str,
    cohort_fingerprint: str,
    chunk_size: int,
    explicit_refresh: bool,
    work_order_path: Path,
) -> InventoryRunManifest:
    kwargs = {
        "parent_snapshot_id": base_snapshot_id or "",
        "canonical_cohort_id": cohort_fingerprint,
        "source_identity": f"filing-catalog-plan:{plan_id}",
        "parser_version": PARSER_FINGERPRINT,
        "chunk_size": chunk_size,
        "refresh_mode": "force" if explicit_refresh else "normal",
        "fetch_mode": "force_refresh" if explicit_refresh else "live",
        "work_order_path": work_order_path,
        "fixture_id": None,
    }
    existing = read_run_manifest(paths)
    if existing is None:
        return write_run_manifest(paths, **kwargs)
    return validate_run_manifest(
        existing,
        run_id=paths.run_id,
        **kwargs,
    )
