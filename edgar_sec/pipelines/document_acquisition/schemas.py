"""Lightweight acquisition handoff and manifest contracts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

RUN_SCHEMA_VERSION = "1"
ACQUISITION_CONTRACT_VERSION = "1"
WORK_ORDER_SCHEMA_VERSION = "1"
RECEIPT_SCHEMA_VERSION = "1"


class PartDescriptor(TypedDict):
    path: str
    row_count: int
    byte_size: int
    sha256: str


class AcquisitionRunManifest(TypedDict):
    run_id: str
    run_schema_version: str
    acquisition_contract_version: str
    target_plan_id: str
    target_plan_digest: str
    bundle_schema_version: int
    target_schema_version: int
    matcher_version: str
    catalog_plan_id: str
    catalog_plan_digest: str
    inventory_snapshot_id: str | None
    inventory_snapshot_digest: str | None
    work_order_schema_version: str
    work_order_parts: list[PartDescriptor]
    target_row_count: int
    executable_count: int
    skipped_count: int
    run_state_schema_version: int
    run_digest: str


@dataclass(frozen=True, slots=True)
class StagedBodyRef:
    run_id: str
    target_id: str
    path: Path
    sha256: str
    byte_size: int
    selected_filename: str | None
    source_response_path: Path | None
    source_response_sha256: str
    source_response_byte_size: int


class BodyConsumptionReceipt(TypedDict):
    receipt_schema_version: str
    run_id: str
    target_id: str
    source_response_sha256: str
    selected_sha256: str
    processing_run_id: str
    consumed_at_utc: str


def target_relation_schema():
    from edgar_sec.pipelines.document_planning.schemas import TARGET_SCHEMA

    return TARGET_SCHEMA


def target_relation_schema_version() -> int:
    from edgar_sec.pipelines.document_planning.schemas import TARGET_SCHEMA_VERSION

    return TARGET_SCHEMA_VERSION


def target_plan_bundle_schema_version() -> int:
    from edgar_sec.pipelines.document_planning.schemas import PLAN_BUNDLE_SCHEMA_VERSION

    return PLAN_BUNDLE_SCHEMA_VERSION


def target_plan_matcher_version() -> str:
    from edgar_sec.pipelines.document_planning.schemas import MATCHER_VERSION

    return MATCHER_VERSION


__all__ = [
    "ACQUISITION_CONTRACT_VERSION",
    "RECEIPT_SCHEMA_VERSION",
    "RUN_SCHEMA_VERSION",
    "WORK_ORDER_SCHEMA_VERSION",
    "AcquisitionRunManifest",
    "BodyConsumptionReceipt",
    "PartDescriptor",
    "StagedBodyRef",
    "target_relation_schema",
    "target_relation_schema_version",
    "target_plan_bundle_schema_version",
    "target_plan_matcher_version",
]
