from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import quote

from edgar_sec.domain.document.route import DocumentRoute
from edgar_sec.domain.forms.common.exhibits import (
    DocumentRoleAssessment,
    EvidenceSpan,
    ExhibitIdentity,
)
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.pipelines.document_acquisition.processing.models import (
    OperationRequest,
    OperationResult,
    ProcessingDiagnostic,
    ProcessingRequest,
    ProcessingResult,
    StagedOutputRef,
)
from edgar_sec.pipelines.document_acquisition.schemas import StagedBodyRef


class ResultProjectionError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ProjectedOperation:
    operation_id: str
    status: str
    operation_fingerprint: str
    representation_id: str | None
    output_sha256: str | None
    output_size: int | None
    handler_id: str | None
    handler_version: str | None
    diagnostics: tuple[ProcessingDiagnostic, ...]
    staged_output_representation: str | None
    staged_output_path: str | None


@dataclass(frozen=True, slots=True)
class ProjectedTarget:
    target_id: str
    accession: str
    form: str
    target_role: str
    target_type: str
    source_origin: str
    document_path: str | None
    selected_filename: str | None
    source_sha256: str
    source_response_sha256: str
    source_size: int
    source_asset_id: str
    source_staged_path: str
    route: DocumentRoute
    effective_path: str
    processing_id: str
    operations: tuple[ProjectedOperation, ...]
    exhibit_assessment: DocumentRoleAssessment | None = None
    exhibit_assessment_fingerprint: str | None = None


@dataclass(slots=True)
class ProcessingResultProjection:
    run_id: str
    fingerprint: str
    _database_path: Path = field(repr=False, compare=False)
    _temporary_directory: tempfile.TemporaryDirectory = field(repr=False, compare=False)
    _closed: bool = field(default=False, init=False, repr=False, compare=False)

    def iter_targets(self) -> Iterator[ProjectedTarget]:
        if self._closed:
            raise ResultProjectionError("projection spool is closed")
        connection = sqlite3.connect(
            f"file:{quote(str(self._database_path.resolve()))}?mode=ro", uri=True
        )
        try:
            for (record,) in connection.execute(
                "SELECT record_json FROM projected_targets ORDER BY target_id"
            ):
                yield _projected_target_from_record(json.loads(record))
        finally:
            connection.close()

    def close(self) -> None:
        if not self._closed:
            self._temporary_directory.cleanup()
            self._closed = True

    def __enter__(self) -> ProcessingResultProjection:
        if self._closed:
            raise ResultProjectionError("projection spool is closed")
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def request_record(request: ProcessingRequest) -> dict[str, object]:
    return {
        "target_id": request.target_id,
        "accession": str(request.accession),
        "form": request.form,
        "filing_date": request.filing_date,
        "report_date": request.report_date,
        "target_role": request.target_role,
        "target_type": request.target_type,
        "document_path": request.document_path,
        "selected_filename": request.selected_filename,
        "source_origin": request.source_origin,
        "body": {
            "run_id": request.body.run_id,
            "target_id": request.body.target_id,
            "path": str(request.body.path),
            "sha256": request.body.sha256,
            "byte_size": request.body.byte_size,
            "selected_filename": request.body.selected_filename,
            "source_response_path": (
                str(request.body.source_response_path)
                if request.body.source_response_path is not None
                else None
            ),
            "source_response_sha256": request.body.source_response_sha256,
            "source_response_byte_size": request.body.source_response_byte_size,
        },
        "operations": [
            {
                "operation_id": item.operation_id,
                "operation": item.operation,
                "requested": item.requested,
                "support_status": item.support_status,
                "source_request_id": item.source_request_id,
                "capability_id": item.capability_id,
                "capability_version": item.capability_version,
                "handler_id": item.handler_id,
                "handler_version": item.handler_version,
                "output_kind": item.output_kind,
            }
            for item in request.operations
        ],
    }


def request_from_record(record: dict[str, object]) -> ProcessingRequest:
    body = record["body"]
    assert isinstance(body, dict)
    operations = record["operations"]
    assert isinstance(operations, list)
    return ProcessingRequest(
        target_id=record["target_id"],
        accession=AccessionNumber.from_any(record["accession"]),
        form=record["form"],
        filing_date=record.get("filing_date"),
        report_date=record.get("report_date"),
        target_role=record["target_role"],
        target_type=record["target_type"],
        document_path=record["document_path"],
        selected_filename=record["selected_filename"],
        source_origin=record["source_origin"],
        body=StagedBodyRef(
            run_id=body["run_id"],
            target_id=body["target_id"],
            path=Path(body["path"]),
            sha256=body["sha256"],
            byte_size=body["byte_size"],
            selected_filename=body["selected_filename"],
            source_response_path=(
                Path(body["source_response_path"])
                if body["source_response_path"] is not None
                else None
            ),
            source_response_sha256=body["source_response_sha256"],
            source_response_byte_size=body["source_response_byte_size"],
        ),
        operations=tuple(OperationRequest(**item) for item in operations),
    )


def result_record(result: ProcessingResult) -> dict[str, object]:
    return {
        "processing_id": result.processing_id,
        "target_id": result.target_id,
        "source_sha256": result.source_sha256,
        "source_asset_id": result.source_asset_id,
        "route": result.route.value
        if isinstance(result.route, DocumentRoute)
        else result.route,
        "effective_path": result.effective_path,
        "exhibit_assessment": (
            asdict(result.exhibit_assessment)
            if result.exhibit_assessment is not None
            else None
        ),
        "exhibit_assessment_fingerprint": result.exhibit_assessment_fingerprint,
        "operation_results": [
            {
                "operation_id": item.operation_id,
                "operation_fingerprint": item.operation_fingerprint,
                "status": item.status,
                "representation_id": item.representation_id,
                "output_sha256": item.output_sha256,
                "output_size": item.output_size,
                "handler_id": item.handler_id,
                "handler_version": item.handler_version,
                "diagnostics": [
                    {"code": diagnostic.code, "detail": diagnostic.detail}
                    for diagnostic in item.diagnostics
                ],
                "staged_output": (
                    {
                        "staging_id": item.staged_output.staging_id,
                        "path": str(item.staged_output.path),
                        "representation": item.staged_output.representation,
                        "output_sha256": item.staged_output.output_sha256,
                        "output_size": item.staged_output.output_size,
                    }
                    if item.staged_output is not None
                    else None
                ),
            }
            for item in result.operation_results
        ],
    }


def _assessment_from_record(record: object) -> DocumentRoleAssessment | None:
    if record is None:
        return None
    if not isinstance(record, dict):
        raise ResultProjectionError("assessment record is invalid")
    data = dict(record)
    data["expected_identity"] = ExhibitIdentity(**data["expected_identity"])
    if data["observed_identity"] is not None:
        data["observed_identity"] = ExhibitIdentity(**data["observed_identity"])
    data["supporting_evidence"] = tuple(
        EvidenceSpan(**item) for item in data["supporting_evidence"]
    )
    data["contradicting_evidence"] = tuple(
        EvidenceSpan(**item) for item in data["contradicting_evidence"]
    )
    return DocumentRoleAssessment(**data)


def result_from_record(record: dict[str, object]) -> ProcessingResult:
    operations = record["operation_results"]
    assert isinstance(operations, list)
    operation_results = []
    for item in operations:
        diagnostics = tuple(
            ProcessingDiagnostic(**diagnostic) for diagnostic in item["diagnostics"]
        )
        output_record = item["staged_output"]
        staged_output = (
            StagedOutputRef(
                staging_id=output_record["staging_id"],
                path=Path(output_record["path"]),
                representation=output_record["representation"],
                output_sha256=output_record["output_sha256"],
                output_size=output_record["output_size"],
            )
            if output_record is not None
            else None
        )
        operation_results.append(
            OperationResult(
                operation_id=item["operation_id"],
                operation_fingerprint=item["operation_fingerprint"],
                status=item["status"],
                representation_id=item["representation_id"],
                output_sha256=item["output_sha256"],
                output_size=item["output_size"],
                handler_id=item["handler_id"],
                handler_version=item["handler_version"],
                diagnostics=diagnostics,
                staged_output=staged_output,
            )
        )
    assessment = _assessment_from_record(record.get("exhibit_assessment"))
    return ProcessingResult(
        processing_id=record["processing_id"],
        target_id=record["target_id"],
        source_sha256=record["source_sha256"],
        source_asset_id=record["source_asset_id"],
        route=DocumentRoute(record["route"]),
        effective_path=record["effective_path"],
        operation_results=tuple(operation_results),
        exhibit_assessment=assessment,
        exhibit_assessment_fingerprint=record.get("exhibit_assessment_fingerprint"),
    )


def projected_target_record(target: ProjectedTarget) -> dict[str, object]:
    return {
        "target_id": target.target_id,
        "accession": target.accession,
        "form": target.form,
        "target_role": target.target_role,
        "target_type": target.target_type,
        "source_origin": target.source_origin,
        "document_path": target.document_path,
        "selected_filename": target.selected_filename,
        "source_sha256": target.source_sha256,
        "source_response_sha256": target.source_response_sha256,
        "source_size": target.source_size,
        "source_asset_id": target.source_asset_id,
        "source_staged_path": target.source_staged_path,
        "route": target.route.value,
        "effective_path": target.effective_path,
        "processing_id": target.processing_id,
        "exhibit_assessment": (
            asdict(target.exhibit_assessment)
            if target.exhibit_assessment is not None
            else None
        ),
        "exhibit_assessment_fingerprint": target.exhibit_assessment_fingerprint,
        "operations": [
            {
                "operation_id": operation.operation_id,
                "status": operation.status,
                "operation_fingerprint": operation.operation_fingerprint,
                "representation_id": operation.representation_id,
                "output_sha256": operation.output_sha256,
                "output_size": operation.output_size,
                "handler_id": operation.handler_id,
                "handler_version": operation.handler_version,
                "staged_output_representation": operation.staged_output_representation,
                "diagnostics": [
                    {"code": item.code, "detail": item.detail}
                    for item in operation.diagnostics
                ],
                "staged_output_path": operation.staged_output_path,
            }
            for operation in target.operations
        ],
    }


def _projected_target_from_record(record: dict[str, object]) -> ProjectedTarget:
    operations = record["operations"]
    assert isinstance(operations, list)
    return ProjectedTarget(
        target_id=record["target_id"],
        accession=record["accession"],
        form=record["form"],
        target_role=record["target_role"],
        target_type=record["target_type"],
        source_origin=record["source_origin"],
        document_path=record["document_path"],
        selected_filename=record["selected_filename"],
        source_sha256=record["source_sha256"],
        source_response_sha256=record["source_response_sha256"],
        source_size=record["source_size"],
        source_asset_id=record["source_asset_id"],
        source_staged_path=record["source_staged_path"],
        route=DocumentRoute(record["route"]),
        effective_path=record["effective_path"],
        processing_id=record["processing_id"],
        exhibit_assessment=_assessment_from_record(record.get("exhibit_assessment")),
        exhibit_assessment_fingerprint=record.get("exhibit_assessment_fingerprint"),
        operations=tuple(
            ProjectedOperation(
                operation_id=operation["operation_id"],
                status=operation["status"],
                operation_fingerprint=operation["operation_fingerprint"],
                representation_id=operation["representation_id"],
                output_sha256=operation["output_sha256"],
                output_size=operation["output_size"],
                handler_id=operation["handler_id"],
                handler_version=operation["handler_version"],
                diagnostics=tuple(
                    ProcessingDiagnostic(**item) for item in operation["diagnostics"]
                ),
                staged_output_representation=operation["staged_output_representation"],
                staged_output_path=operation["staged_output_path"],
            )
            for operation in operations
        ),
    )


def fingerprint_targets(run_id: str, targets: Iterable[ProjectedTarget]) -> str:
    digest = hashlib.sha256()
    digest.update(b'{"run_id":')
    digest.update(canonical_json(run_id).encode("utf-8"))
    digest.update(b',"targets":[')
    for index, target in enumerate(targets):
        if index:
            digest.update(b",")
        digest.update(canonical_json(projected_target_record(target)).encode("utf-8"))
    digest.update(b"]}")
    return digest.hexdigest()


__all__ = [
    "ProcessingResultProjection",
    "ProjectedOperation",
    "ProjectedTarget",
    "ResultProjectionError",
]
