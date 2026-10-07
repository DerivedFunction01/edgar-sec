"""Transient identity and atomic validation for catalog-plan runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edgar_sec.foundation.hashing import file_sha256, sha256_text
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.pipelines.document_storage.catalog_plan import (
    WORK_ORDER_VERSION,
    CatalogPlan,
)
from edgar_sec.pipelines.document_storage.checkpoint import DOCUMENT_SNAPSHOT_SCHEMA
from edgar_sec.pipelines.document_storage.paths import MANIFEST_FILE_NAME
from edgar_sec.pipelines.document_storage.processor import DocumentProcessor
from edgar_sec.pipelines.document_storage.execution import WORKER_SCHEMA_VERSION

RUN_MANIFEST_VERSION = 1


class RunManifestError(RuntimeError):
    """A catalog run's saved identity is missing, invalid, or mismatched."""


@dataclass(frozen=True, slots=True)
class CatalogRunIdentity:
    """Inputs that must remain stable for a catalog run to resume."""

    values: dict[str, Any]


def catalog_run_identity(
    plan: CatalogPlan,
    *,
    run_id: str,
    mode: str,
    fixture_ids: tuple[str, ...],
    processor: DocumentProcessor,
) -> CatalogRunIdentity:
    fingerprint = getattr(processor, "processor_fingerprint", "custom:unspecified")
    schema_identity = sha256_text(
        canonical_json(
            [
                {
                    "name": field.name,
                    "type": str(field.type),
                    "nullable": field.nullable,
                }
                for field in DOCUMENT_SNAPSHOT_SCHEMA
            ]
        )
    )
    sources = [
        {
            "path": path.relative_to(plan.plan_dir).as_posix(),
            "sha256": file_sha256(path),
        }
        for path in plan.source_files
    ]
    return CatalogRunIdentity(
        values={
            "run_id": run_id,
            "plan": plan.canonical_metadata,
            "locator_count": plan.metadata.locator_count,
            "chunk_count": plan.chunk_count,
            "sources": sources,
            "work_order_version": WORK_ORDER_VERSION,
            "chunk_size": plan.chunk_size,
            "processor_fingerprint": fingerprint,
            "worker_schema_version": WORKER_SCHEMA_VERSION,
            "checkpoint_schema_sha256": schema_identity,
            "fetch_mode": mode,
            "fixture_ids": list(fixture_ids),
        }
    )


def create_or_validate_manifest(
    run_dir: Path, run_id: str, identity: CatalogRunIdentity
) -> str:
    """Atomically create a new run manifest or validate an existing one."""
    manifest_path = run_dir / MANIFEST_FILE_NAME
    manifest = {
        "manifest_version": RUN_MANIFEST_VERSION,
        "run_id": run_id,
        "identity": identity.values,
    }
    if run_dir.exists():
        try:
            saved = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RunManifestError(
                f"existing catalog run has no valid manifest: {manifest_path}"
            ) from exc
        if not isinstance(saved, dict) or saved != manifest:
            raise RunManifestError(
                f"catalog run manifest does not match current inputs: {manifest_path}"
            )
        return "resumed"

    run_dir.mkdir(parents=True, exist_ok=False)
    atomic_write_json(manifest_path, manifest, canonical=True)
    return "fresh"


__all__ = [
    "RUN_MANIFEST_VERSION",
    "CatalogRunIdentity",
    "RunManifestError",
    "catalog_run_identity",
    "create_or_validate_manifest",
]
