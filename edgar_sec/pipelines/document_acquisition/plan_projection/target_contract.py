"""Shared contract types and schema pins for target-bundle validation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edgar_sec.pipelines.document_acquisition.schemas import (
    target_plan_bundle_schema_version,
    target_plan_matcher_version,
    target_relation_schema,
    target_relation_schema_version,
)

_TARGET_SCHEMA = target_relation_schema()
_TARGET_SCHEMA_VERSION = target_relation_schema_version()
_PLAN_BUNDLE_SCHEMA_VERSION = target_plan_bundle_schema_version()
_TARGET_MATCHER_VERSION = target_plan_matcher_version()


class TargetPlanError(ValueError):
    """A target bundle or its work-order projection is invalid."""


@dataclass(frozen=True, slots=True)
class WorkOrderProjection:
    plan_id: str
    plan_digest: str
    bundle_schema_version: int
    matcher_version: str
    target_schema_version: int
    target_operation_schema_version: int
    source_request_schema_version: int
    operation_input_schema_version: int
    resolved_operation_schema_version: int
    catalog_plan_id: str
    catalog_plan_digest: str
    inventory_snapshot_id: str | None
    inventory_snapshot_digest: str | None
    target_row_count: int
    executable_count: int
    skipped_count: int
    parquet_path: Path
    relation_parts: dict[str, list[dict[str, Any]]]
    relation_counts: dict[str, int]
    relation_digests: dict[str, str]


@dataclass(frozen=True, slots=True)
class _ValidatedPlan:
    root: Path
    manifest: dict[str, Any]
    parts: tuple[Path, ...]
    relations: dict[str, tuple[Path, ...]]
