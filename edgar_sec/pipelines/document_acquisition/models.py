"""Typed values for acquisition attempts, resolutions, and run reports."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

SourceOrigin = Literal["inventory_index", "catalog_direct"]
RetrievalMode = Literal["direct_url", "bundle_sequence"]
AcquisitionSource = Literal["live_sec", "fixture_replay"]
AttemptKind = Literal["document_body", "lazy_index"]
AcquisitionStatus = Literal[
    "pending",
    "acquired",
    "not_filed",
    "required_missing",
    "ambiguous",
    "failed",
    "skipped",
]
RunStatus = Literal[
    "ready",
    "running",
    "interrupted",
    "complete",
    "needs_retry",
    "complete_with_errors",
    "invalid",
]
BodyLifecycle = Literal["staged", "consumed"]


@dataclass(frozen=True, slots=True)
class AcquisitionPolicy:
    max_response_bytes: int
    requested_workers: int | None = None
    retain_response_evidence: bool = False

    def __post_init__(self) -> None:
        if (
            isinstance(self.max_response_bytes, bool)
            or not isinstance(self.max_response_bytes, int)
            or self.max_response_bytes < 1
        ):
            raise ValueError("max_response_bytes must be a positive finite integer")
        if self.requested_workers is not None and (
            isinstance(self.requested_workers, bool)
            or not isinstance(self.requested_workers, int)
            or self.requested_workers < 1
        ):
            raise ValueError("requested_workers must be a positive integer")
        if type(self.retain_response_evidence) is not bool:
            raise ValueError("retain_response_evidence must be a boolean")


@dataclass(frozen=True, slots=True)
class AcquisitionAttempt:
    attempt_id: str
    target_id: str
    attempt_number: int
    attempt_kind: AttemptKind
    source: AcquisitionSource
    requested_url: str
    outcome: Literal["acquired", "not_filed", "required_missing", "ambiguous", "failed"]
    retryable: bool
    error_code: str | None
    http_status: int | None
    final_url: str | None
    started_at_utc: str
    finished_at_utc: str
    source_sha256: str | None
    source_byte_size: int | None
    source_body_relative_path: str | None
    selected_sha256: str | None
    selected_byte_size: int | None
    selected_body_relative_path: str | None


@dataclass(frozen=True, slots=True)
class TargetSlotResolution:
    resolution_schema_version: str
    resolution_id: str
    run_id: str
    target_id: str
    target_role: Literal["primary", "exhibit", "data_file", "graphic", "package"]
    target_type: str
    selector: Literal["submitted_primary", "exact_form_with_lazy_index"]
    expected_statutory_type: str
    initial_sequence: int
    index_document_type: str | None
    index_primary_designation: bool | None
    initial_observed_body_type: str | None
    screen_kind: Literal["none", "sgml_type", "html_cover"]
    screen_result: Literal["not_run", "form_match", "type_mismatch", "unverifiable"]
    evaluator_version: str | None
    initial_body_sha256: str
    index_attempt_id: str | None
    index_response_sha256: str | None
    index_parser_version: str | None
    matching_entry_ids: tuple[str, ...]
    selected_sequence: int | None
    selected_retrieval_mode: RetrievalMode | None
    selected_url: str | None
    result: Literal[
        "accepted_sequence_1",
        "recovered",
        "not_filed",
        "required_missing",
        "ambiguous",
        "failed",
    ]


@dataclass(frozen=True, slots=True)
class AcquisitionOutcome:
    target_id: str
    source: AcquisitionSource | None
    status: AcquisitionStatus
    attempt_count: int
    last_attempt_id: str | None
    error_code: str | None
    retryable: bool
    source_sha256: str | None
    source_byte_size: int | None
    source_body_relative_path: str | None
    selected_sha256: str | None
    selected_byte_size: int | None
    body_lifecycle: BodyLifecycle | None
    selected_body_relative_path: str | None


@dataclass(frozen=True, slots=True)
class AcquisitionStatusCounts:
    target_counts: Mapping[AcquisitionStatus, int]
    retryable_failure_count: int
    non_retryable_failure_count: int


@dataclass(frozen=True, slots=True)
class RunLockInfo:
    host: str
    pid: int
    started_at_utc: str
    owner_token: str


@dataclass(frozen=True, slots=True)
class ProjectedAcquisitionRun:
    run_id: str
    manifest: Mapping[str, object]
    executable_count: int
    skipped_count: int
    work_order_sha256: str
    reused: bool


@dataclass(frozen=True, slots=True)
class AcquisitionStatusReport:
    run_id: str
    state: RunStatus
    target_counts: Mapping[AcquisitionStatus, int]
    retryable_failure_count: int
    non_retryable_failure_count: int
    active_lock: RunLockInfo | None
    invalid_reason: str | None


@dataclass(frozen=True, slots=True)
class AcquisitionRunReport:
    run_id: str
    state: RunStatus
    target_counts: Mapping[AcquisitionStatus, int]
    attempted_count: int
    retryable_failure_count: int
    non_retryable_failure_count: int
    cancelled: bool


__all__ = [
    "AcquisitionAttempt",
    "AcquisitionOutcome",
    "AcquisitionPolicy",
    "AcquisitionRunReport",
    "AcquisitionSource",
    "AcquisitionStatus",
    "AcquisitionStatusCounts",
    "AcquisitionStatusReport",
    "AttemptKind",
    "BodyLifecycle",
    "ProjectedAcquisitionRun",
    "RetrievalMode",
    "RunLockInfo",
    "RunStatus",
    "SourceOrigin",
    "TargetSlotResolution",
]
