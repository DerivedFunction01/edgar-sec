from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.pipelines.document_acquisition.models import (
    AcquisitionAttempt,
    AcquisitionStatus,
    OperationAttempt,
)


@dataclass(frozen=True, slots=True)
class WorkOrderTargetSeed:
    target_id: str
    executable: bool
    skip_reason: str | None


@dataclass(frozen=True, slots=True)
class WorkOrderOperationSeed:
    operation_id: str
    target_id: str
    operation: str
    requested: bool
    request_mode: str
    selected: bool
    source_request_id: str | None
    input_ordinal: int | None
    input_role: str | None
    support_status: str
    support_reason: str | None
    capability_id: str | None
    capability_version: str | None
    handler_id: str | None
    handler_version: str | None
    output_kind: str | None


@dataclass(frozen=True, slots=True)
class OperationState:
    operation_id: str
    target_id: str
    operation: str
    requested: bool
    request_mode: str
    selected: bool
    source_request_id: str | None
    input_ordinal: int | None
    input_role: str | None
    support_status: str
    support_reason: str | None
    capability_id: str | None
    capability_version: str | None
    handler_id: str | None
    handler_version: str | None
    output_kind: str | None
    status: str
    retryable: bool
    attempt_count: int
    last_attempt_id: str | None
    error_code: str | None


__all__ = [
    "AttemptEvidenceGroup",
    "OperationState",
    "WorkOrderOperationSeed",
    "TargetState",
    "WorkOrderTargetSeed",
]


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


@dataclass(frozen=True, slots=True)
class AttemptEvidenceGroup:
    initial_attempt: AcquisitionAttempt
    lazy_index_attempt: AcquisitionAttempt | None
    selected_body_attempt: AcquisitionAttempt | None
    resolution: TargetSlotResolution | None


def _target_state_from_row(row: tuple[object, ...]) -> TargetState:
    return TargetState(
        target_id=row[0],
        executable=bool(row[1]),
        skip_reason=row[2],
        outcome=row[3],
        source=row[4],
        retryable=bool(row[5]),
        attempt_count=row[6],
        last_attempt_id=row[7],
        error_code=row[8],
        source_sha256=row[9],
        source_byte_size=row[10],
        source_body_relative_path=row[11],
        selected_sha256=row[12],
        selected_byte_size=row[13],
        selected_body_relative_path=row[14],
    )


def _acquisition_attempt_from_row(row: tuple[object, ...]) -> AcquisitionAttempt:
    return AcquisitionAttempt(
        attempt_id=row[0],
        target_id=row[1],
        attempt_number=row[2],
        attempt_kind=row[3],
        source=row[4],
        requested_url=row[5],
        outcome=row[6],
        retryable=bool(row[7]),
        error_code=row[8],
        http_status=row[9],
        final_url=row[10],
        started_at_utc=row[11],
        finished_at_utc=row[12],
        source_sha256=row[13],
        source_byte_size=row[14],
        source_body_relative_path=row[15],
        selected_sha256=row[16],
        selected_byte_size=row[17],
        selected_body_relative_path=row[18],
        selected_filename=row[19],
    )


def _operation_attempt_from_row(row: tuple[object, ...]) -> OperationAttempt:
    return OperationAttempt(
        attempt_id=row[0],
        operation_id=row[1],
        attempt_number=row[2],
        outcome=row[3],
        retryable=bool(row[4]),
        error_code=row[5],
        started_at_utc=row[6],
        finished_at_utc=row[7],
    )


def _operation_state_from_row(row: tuple[object, ...]) -> OperationState:
    return OperationState(
        operation_id=row[0],
        target_id=row[1],
        operation=row[2],
        requested=bool(row[3]),
        request_mode=row[4],
        selected=bool(row[5]),
        source_request_id=row[6],
        input_ordinal=row[7],
        input_role=row[8],
        support_status=row[9],
        support_reason=row[10],
        capability_id=row[11],
        capability_version=row[12],
        handler_id=row[13],
        handler_version=row[14],
        output_kind=row[15],
        status=row[16],
        retryable=bool(row[17]),
        attempt_count=row[18],
        last_attempt_id=row[19],
        error_code=row[20],
    )
