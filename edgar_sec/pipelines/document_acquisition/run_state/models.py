from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.pipelines.document_acquisition.models import AcquisitionStatus


@dataclass(frozen=True, slots=True)
class WorkOrderTargetSeed:
    target_id: str
    executable: bool
    skip_reason: str | None


@dataclass(frozen=True, slots=True)
class TargetState:
    target_id: str
    executable: bool
    skip_reason: str | None
    outcome: AcquisitionStatus
    source: str | None
    retryable: bool
    attempt_count: int
    last_attempt_id: str | None
    error_code: str | None
    source_sha256: str | None
    source_byte_size: int | None
    source_body_relative_path: str | None
    selected_sha256: str | None
    selected_byte_size: int | None
    selected_body_relative_path: str | None


__all__ = ["TargetState", "WorkOrderTargetSeed"]
