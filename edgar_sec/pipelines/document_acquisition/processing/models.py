from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from edgar_sec.domain.document.route import DocumentRoute
from edgar_sec.domain.forms.common.exhibits import DocumentRoleAssessment
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.foundation.hashing import is_sha256_hex_digest
from edgar_sec.pipelines.document_acquisition.schemas import (
    FixtureBodyRef,
    StagedBodyRef,
)

OperationName = Literal["raw", "render_to_txt", "render_to_xml"]
OperationSupport = Literal["supported", "unsupported", "not_evaluated"]
OperationStatus = Literal[
    "not_requested", "unsupported", "blocked", "available", "failed"
]


@dataclass(frozen=True, slots=True)
class OperationRequest:
    operation_id: str
    operation: OperationName
    requested: bool
    support_status: OperationSupport
    source_request_id: str | None
    capability_id: str | None
    capability_version: str | None
    handler_id: str | None
    handler_version: str | None
    output_kind: str | None


@dataclass(frozen=True, slots=True)
class ProcessingRequest:
    target_id: str
    accession: AccessionNumber
    form: str
    target_role: Literal["primary", "exhibit", "data_file", "graphic", "package"]
    target_type: str
    document_path: str | None
    selected_filename: str | None
    source_origin: Literal["inventory_index", "catalog_direct"]
    body: StagedBodyRef | FixtureBodyRef
    operations: tuple[OperationRequest, ...]
    filing_date: str | None = None
    report_date: str | None = None


@dataclass(frozen=True, slots=True)
class ProcessingDiagnostic:
    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class StagedOutputRef:
    staging_id: str
    path: Path
    representation: Literal["raw", "text_normalized", "xml"]
    output_sha256: str
    output_size: int


@dataclass(frozen=True, slots=True)
class OperationResult:
    operation_id: str
    operation_fingerprint: str
    status: OperationStatus
    representation_id: str | None
    output_sha256: str | None
    output_size: int | None
    handler_id: str | None
    handler_version: str | None
    diagnostics: tuple[ProcessingDiagnostic, ...]
    staged_output: StagedOutputRef | None


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    processing_id: str
    target_id: str
    source_sha256: str
    source_asset_id: str
    route: DocumentRoute
    effective_path: str
    operation_results: tuple[OperationResult, ...]
    exhibit_assessment: DocumentRoleAssessment | None = None
    exhibit_assessment_fingerprint: str | None = None

    def __post_init__(self) -> None:
        if (self.exhibit_assessment is None) != (
            self.exhibit_assessment_fingerprint is None
        ):
            raise ValueError("assessment and diagnostic fingerprint must be paired")
        if self.exhibit_assessment_fingerprint is not None and not is_sha256_hex_digest(
            self.exhibit_assessment_fingerprint
        ):
            raise ValueError("diagnostic fingerprint is invalid")


__all__ = [
    "OperationRequest",
    "OperationResult",
    "ProcessingDiagnostic",
    "ProcessingRequest",
    "ProcessingResult",
    "StagedOutputRef",
]
