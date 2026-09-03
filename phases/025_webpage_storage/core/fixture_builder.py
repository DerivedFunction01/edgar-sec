"""Populate an offline SQLite fixture from a target plan and live SEC client."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from defs.runtime.paths import resolve_paths
from defs.runtime.resources import derive_resources
from defs.sec_http import SecHttpClient, make_sec_http_client
from defs.sql import Select, SqlDialect, Star, Table, make_sql_executor
from defs.storage import atomic_write_json, load_json

from .chunk_worker import process_chunk
from .fetcher import LiveSecArchiveFetcher
from .pipeline import load_targets
from .schemas import (
    ACQUISITION_FAILURES_TABLE,
    DOCUMENT_BLOBS_TABLE,
    doc_id,
)

FIXTURE_MANIFEST_SCHEMA_VERSION = 1


def _fixture_rows(path: Path, table: str) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    executor = make_sql_executor(path, dialect=SqlDialect.SQLITE)
    try:
        return executor.query(
            executor.compiler.compile(Select(source=Table(table), projection=(Star(),)))
        )
    finally:
        executor.close()


def _plan_fingerprint(plan: dict[str, Any], locators: list) -> str:
    value = plan.get("plan_fingerprint")
    if value:
        return str(value)
    payload = {
        "plan_id": plan.get("plan_id"),
        "catalog_id": plan.get("catalog_id"),
        "locators": [
            [locator.accession, locator.document_path] for locator in locators
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:32]


def _load_fixture_manifest(
    path: Path, fixture_id: str, *, unknown_lineage: bool
) -> dict[str, Any]:
    manifest = load_json(path, default=None)
    if manifest is None:
        return {
            "fixture_manifest_schema_version": FIXTURE_MANIFEST_SCHEMA_VERSION,
            "fixture_id": fixture_id,
            "storage_format": "sqlite",
            "lineage_status": "unknown" if unknown_lineage else "tracked",
            "catalog_id": None,
            "policy_corpus": None,
            "forms": [],
            "plan_history": [],
        }
    if not isinstance(manifest, dict):
        raise ValueError(f"fixture manifest must contain an object: {path}")
    if manifest.get("fixture_id") not in (None, fixture_id):
        raise ValueError("fixture manifest belongs to a different fixture ID")
    manifest.setdefault("plan_history", [])
    manifest.setdefault("lineage_status", "unknown")
    return manifest


def _validate_fixture_compatibility(
    manifest: dict[str, Any], plan: dict[str, Any]
) -> None:
    catalog_id = plan.get("catalog_id")
    if (
        manifest.get("catalog_id")
        and catalog_id
        and manifest["catalog_id"] != catalog_id
    ):
        raise ValueError("fixture and plan use different catalogs")
    policy_corpus = plan.get("policy_corpus")
    if (
        manifest.get("policy_corpus")
        and policy_corpus
        and manifest["policy_corpus"] != policy_corpus
    ):
        raise ValueError("fixture and plan use different policy corpora")
    seed_fingerprint = plan.get("seed_fingerprint")
    if (
        manifest.get("seed_fingerprint")
        and seed_fingerprint
        and manifest["seed_fingerprint"] != seed_fingerprint
    ):
        raise ValueError("fixture and plan use different seed CIK sets")
    plan_forms = {str(form).upper() for form in plan.get("forms", [])}
    manifest_forms = {str(form).upper() for form in manifest.get("forms", [])}
    if manifest_forms and plan_forms and manifest_forms != plan_forms:
        raise ValueError("fixture and plan use different form selections")


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
    retry_failures: bool = False,
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
    fixture_paths = resolve_paths().fixture(resolved_id, dialect="sqlite")
    fixture_db = fixture_paths.db_path
    fixture_paths.ensure_layout()

    locators, _, plan = load_targets(plan_dir)
    if limit is not None and limit > 0:
        locators = locators[:limit]

    fixture_manifest = _load_fixture_manifest(
        fixture_paths.manifest_path,
        resolved_id,
        unknown_lineage=fixture_db.is_file(),
    )
    _validate_fixture_compatibility(fixture_manifest, plan)
    before_blob_rows = _fixture_rows(fixture_db, DOCUMENT_BLOBS_TABLE)
    before_failure_rows = _fixture_rows(fixture_db, ACQUISITION_FAILURES_TABLE)
    current_doc_ids = {
        doc_id(locator.accession, locator.document_path) for locator in locators
    }
    before_blob_ids = {str(row["doc_id"]) for row in before_blob_rows}
    before_failure_ids = {str(row["doc_id"]) for row in before_failure_rows}

    client = http_client or _build_default_http_client(workers)
    fetcher = LiveSecArchiveFetcher(client)

    chunk_result = process_chunk(
        chunk_id=f"fixture-{resolved_id}",
        worker_id="fixture-builder",
        locators=locators,
        occurrences=(),
        fetcher=fetcher,
        output_path=fixture_db,
        progress=progress,
        fetch_workers=workers,
        allow_append=True,
        retry_failures=retry_failures,
    )

    after_failure_rows = _fixture_rows(fixture_db, ACQUISITION_FAILURES_TABLE)
    after_failure_ids = {str(row["doc_id"]) for row in after_failure_rows}
    newly_fetched = max(0, chunk_result.blob_count - len(before_blob_rows))
    retried_count = len(current_doc_ids & before_failure_ids) if retry_failures else 0
    plan_id = str(plan.get("plan_id") or f"legacy-{_plan_fingerprint(plan, locators)}")
    history_entry = {
        "plan_id": plan_id,
        "plan_fingerprint": _plan_fingerprint(plan, locators),
        "parent_plan_id": plan.get("parent_plan_id"),
        "target_units": plan.get("target_units"),
        "target_locators": len(locators),
        "added_locators_count": plan.get("added_locators_count", len(locators)),
        "newly_fetched": newly_fetched,
        "cached_count": len(current_doc_ids & before_blob_ids),
        "failed_count": len(current_doc_ids & after_failure_ids),
        "retried_count": retried_count,
        "completed_at": datetime.now(UTC).isoformat(),
    }
    history = [
        entry
        for entry in fixture_manifest.get("plan_history", [])
        if entry.get("plan_id") != plan_id
    ]
    history.append(history_entry)
    fixture_manifest.update(
        {
            "fixture_manifest_schema_version": FIXTURE_MANIFEST_SCHEMA_VERSION,
            "fixture_id": resolved_id,
            "storage_format": "sqlite",
            "catalog_id": fixture_manifest.get("catalog_id") or plan.get("catalog_id"),
            "policy_corpus": fixture_manifest.get("policy_corpus")
            or plan.get("policy_corpus"),
            "seed_fingerprint": fixture_manifest.get("seed_fingerprint")
            or plan.get("seed_fingerprint"),
            "forms": fixture_manifest.get("forms") or plan.get("forms", []),
            "blob_count": chunk_result.blob_count,
            "failure_count": len(after_failure_rows),
            "plan_history": history,
            "updated_at": datetime.now(UTC).isoformat(),
        }
    )
    atomic_write_json(fixture_paths.manifest_path, fixture_manifest)

    return {
        "fixture_id": resolved_id,
        "database": str(fixture_db),
        "target_locators": chunk_result.locator_count,
        "total_persisted": chunk_result.blob_count,
        "newly_fetched": newly_fetched,
        "cached_count": len(current_doc_ids & before_blob_ids),
        "failed_count": len(current_doc_ids & after_failure_ids),
        "retried_count": retried_count,
    }


__all__ = ["FIXTURE_MANIFEST_SCHEMA_VERSION", "fill_fixture"]
