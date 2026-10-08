"""Shared CLI helper functions for document inventory commands."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from edgar_sec.foundation.hashing import file_sha256, sha256_text
from edgar_sec.foundation.runtime.paths import PLAN_FILE_NAME, resolve_paths
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.pipelines.document_inventory.cohort import (
    project_cohort,
    read_catalog_observations,
)
from edgar_sec.pipelines.document_inventory.discovery import discover_plans
from edgar_sec.pipelines.document_inventory.fixture_store.models import (
    FixtureContribution,
)
from edgar_sec.pipelines.document_inventory.paths import (
    resolve_filing_catalog_paths,
)

ARCHIVE_BASE_URL = "https://www.sec.gov/Archives/edgar/data"


def resolve_artifacts_root(value: str | Path | None = None) -> Path:
    """Resolve artifacts root directory."""
    if value:
        return Path(value).expanduser().resolve()
    return resolve_paths().artifacts_root.resolve()


def resolve_plan(
    root: Path, plan_id: str
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    """Resolve and validate a catalog plan and its metadata."""
    catalog_paths = resolve_filing_catalog_paths(root)
    plan = next(
        (item for item in discover_plans(root) if item["plan_id"] == plan_id), None
    )
    if plan is None:
        raise ValueError(f"catalog plan is not published: {plan_id}")
    plan_file = catalog_paths.plan_dir(plan_id) / PLAN_FILE_NAME
    try:
        metadata = json.loads(plan_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"catalog plan is unreadable: {plan_id}") from exc
    if not isinstance(metadata, dict):
        raise ValueError(f"catalog plan is malformed: {plan_id}")
    return plan, metadata, plan_file


def cohort_for_plan(root: Path, plan_id: str, limit: int | None):
    """Project and bound cohort for the requested catalog plan."""
    plan, metadata, plan_file = resolve_plan(root, plan_id)
    observations = list(
        read_catalog_observations(
            resolve_filing_catalog_paths(root).plan_dir(plan_id),
            f"plan:{plan_id}",
            "catalog_plan",
        )
    )
    cohort = project_cohort(observations, archive_base_url=ARCHIVE_BASE_URL)
    if limit is not None and len(cohort.work_items) > limit:
        selected = cohort.work_items[:limit]
        selected_accessions = {str(item.accession) for item in selected}
        cohort = replace(
            cohort,
            observations=tuple(
                item
                for item in cohort.observations
                if str(item.accession) in selected_accessions
            ),
            accessions=tuple(
                item
                for item in cohort.accessions
                if str(item.accession) in selected_accessions
            ),
            sources=tuple(
                item
                for item in cohort.sources
                if str(item.accession) in selected_accessions
            ),
            work_items=selected,
        )
    fingerprint = sha256_text(
        canonical_json(
            {
                "catalog_id": plan.get("catalog_id"),
                "limit": limit,
                "plan_file_sha256": file_sha256(plan_file),
                "plan_id": plan_id,
                "selected_accessions": len(cohort.work_items),
                "scope": plan.get("scope"),
            }
        )
    )
    contribution = FixtureContribution(
        plan_id=plan_id,
        catalog_id=str(plan.get("catalog_id") or ""),
        scope=str(plan.get("scope") or "unknown"),
        plan_schema_version=str(metadata.get("schema_version") or "unknown"),
        request_fingerprint=fingerprint,
        accession_count=len(cohort.work_items),
    )
    return plan, cohort, contribution
