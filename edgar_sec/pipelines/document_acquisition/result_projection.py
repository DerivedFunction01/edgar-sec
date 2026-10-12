from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath

import pyarrow as pa

from edgar_sec.domain.document.route import DocumentRoute
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.domain.sec_urls import validate_archive_url
from edgar_sec.foundation.hashing import is_sha256_hex_digest
from edgar_sec.foundation.io import DEFAULT_IO_CHUNK_SIZE
from edgar_sec.foundation.runtime.paths import validate_safe_id
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.pipelines.document_acquisition.body_handoff import (
    BodyHandoffError,
    get_staged_body_ref,
)
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths
from edgar_sec.pipelines.document_acquisition.processing_models import (
    OperationRequest,
    OperationResult,
    ProcessingDiagnostic,
    ProcessingRequest,
    ProcessingResult,
    StagedOutputRef,
)
from edgar_sec.pipelines.document_acquisition.run_validation import (
    iter_work_order_batches,
    load_validated_work_order,
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


@dataclass(frozen=True, slots=True)
class ProcessingResultProjection:
    run_id: str
    fingerprint: str
    targets: tuple[ProjectedTarget, ...]


_TERMINAL_STATUSES = frozenset(
    {"not_requested", "unsupported", "blocked", "available", "failed"}
)
_EXECUTION_STATUSES = frozenset({"available", "failed", "blocked", "unsupported"})


def _request_index(
    requests: tuple[ProcessingRequest, ...], run_id: str
) -> dict[str, ProcessingRequest]:
    indexed: dict[str, ProcessingRequest] = {}
    for request in requests:
        try:
            validate_safe_id(request.target_id, "target_id")
        except ValueError as error:
            raise ResultProjectionError("processing target ID is invalid") from error
        if request.target_id in indexed:
            raise ResultProjectionError("processing request target is duplicated")
        if request.body.run_id != run_id or request.body.target_id != request.target_id:
            raise ResultProjectionError(
                "processing request body identity is inconsistent"
            )
        if not request.operations:
            raise ResultProjectionError("processing request has no explicit operations")
        operation_ids = set()
        for operation in request.operations:
            _validate_operation_request(operation)
            if operation.operation_id in operation_ids:
                raise ResultProjectionError(
                    "processing request operation is duplicated"
                )
            operation_ids.add(operation.operation_id)
        indexed[request.target_id] = request
    return indexed


def _result_index(
    results: tuple[ProcessingResult, ...],
) -> dict[str, ProcessingResult]:
    indexed: dict[str, ProcessingResult] = {}
    processing_ids: set[str] = set()
    for result in results:
        try:
            validate_safe_id(result.target_id, "target_id")
            validate_safe_id(result.processing_id, "processing_id")
        except ValueError as error:
            raise ResultProjectionError(
                "processing result identity is invalid"
            ) from error
        if result.target_id in indexed:
            raise ResultProjectionError("processing result target is duplicated")
        if result.processing_id in processing_ids:
            raise ResultProjectionError("processing ID is duplicated")
        processing_ids.add(result.processing_id)
        indexed[result.target_id] = result
    return indexed


def _validate_operation_request(operation: OperationRequest) -> None:
    try:
        validate_safe_id(operation.operation_id, "operation_id")
    except ValueError as error:
        raise ResultProjectionError("operation ID is invalid") from error
    if operation.operation not in {"raw", "render_to_txt", "render_to_xml"}:
        raise ResultProjectionError("operation name is invalid")
    if type(operation.requested) is not bool:
        raise ResultProjectionError("operation requested flag is invalid")
    if operation.support_status not in {"supported", "unsupported", "not_evaluated"}:
        raise ResultProjectionError("operation support status is invalid")


def _work_targets(
    paths: AcquisitionPaths,
    run_id: str,
    requests: dict[str, ProcessingRequest],
) -> dict[str, dict[str, object]]:
    try:
        parts = load_validated_work_order(paths, run_id)
        rows: dict[str, dict[str, object]] = {}
        for batch in iter_work_order_batches(parts):
            for row in batch:
                target_id = row.get("target_id")
                if target_id not in requests:
                    continue
                if target_id in rows:
                    raise ResultProjectionError("target is duplicated in work order")
                rows[target_id] = row
    except ResultProjectionError:
        raise
    except (OSError, ValueError, TypeError, sqlite3.Error, pa.ArrowException) as error:
        raise ResultProjectionError("validated work order is unavailable") from error
    missing = requests.keys() - rows.keys()
    if missing:
        raise ResultProjectionError(
            "processing request target is absent from work order"
        )
    return rows


def _validate_work_target(request: ProcessingRequest, row: dict[str, object]) -> None:
    accession = AccessionNumber.from_any(request.accession)
    if (
        AccessionNumber.from_any(str(row["accession"])) != accession
        or row["form"] != request.form
        or row["target_role"] != request.target_role
        or row["target_type"] != request.target_type
        or row["source_origin"] != request.source_origin
        or row["executable"] is not True
        or row["status"] != "matched"
    ):
        raise ResultProjectionError("processing request differs from work order")
    if row["retrieval_mode"] not in {"direct_url", "bundle_sequence"}:
        raise ResultProjectionError("work-order target is not processable")
    if row["retrieval_mode"] == "bundle_sequence":
        raise ResultProjectionError(
            "bundle result projection requires committed selected-filename evidence"
        )
    try:
        target = validate_archive_url(str(row["target_url"]), accession)
    except ValueError as error:
        raise ResultProjectionError("work-order target URL is invalid") from error
    if request.document_path != target.document_path:
        raise ResultProjectionError("processing path differs from work order")


def _relative_staging_path(path: Path, paths: AcquisitionPaths, run_id: str) -> str:
    try:
        if not path.is_absolute():
            raise ValueError("staged path is not absolute")
        run_dir = paths.run_dir(run_id)
        if stat.S_ISLNK(run_dir.lstat().st_mode):
            raise ValueError("run directory is a symlink")
        staging_root = paths.run_staging_root(run_id)
        if stat.S_ISLNK(staging_root.lstat().st_mode):
            raise ValueError("staging root is a symlink")
        relative = path.relative_to(staging_root)
        if any(part in {"", ".", ".."} for part in relative.parts):
            raise ValueError("staged path is not canonical")
        resolved_root = staging_root.resolve(strict=True)
        resolved_path = path.resolve(strict=True)
        resolved_path.relative_to(resolved_root)
        if not stat.S_ISREG(path.lstat().st_mode):
            raise ValueError("staged path is not a regular file")
        for parent in path.parents:
            if parent == staging_root.parent:
                break
            if stat.S_ISLNK(parent.lstat().st_mode):
                raise ValueError("staged path contains a symlink")
    except (OSError, ValueError) as error:
        raise ResultProjectionError(
            "staged output path escapes the run staging root"
        ) from error
    return path.relative_to(run_dir).as_posix()


def _verify_staged_output(
    output: StagedOutputRef,
    *,
    paths: AcquisitionPaths,
    run_id: str,
    processing_id: str,
) -> str:
    if output.staging_id != processing_id:
        raise ResultProjectionError("staged output owner differs from processing ID")
    if not is_sha256_hex_digest(output.output_sha256) or output.output_size < 0:
        raise ResultProjectionError("staged output digest or size is invalid")
    relative_path = _relative_staging_path(output.path, paths, run_id)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(output.path, flags)
    except OSError as error:
        raise ResultProjectionError("staged output cannot be opened safely") from error
    digest = hashlib.sha256()
    size = 0
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ResultProjectionError("staged output is not a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            while chunk := stream.read(DEFAULT_IO_CHUNK_SIZE):
                digest.update(chunk)
                size += len(chunk)
    finally:
        os.close(descriptor)
    if (digest.hexdigest(), size) != (output.output_sha256, output.output_size):
        raise ResultProjectionError("staged output digest or size differs from result")
    return relative_path


def _effective_path(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ResultProjectionError("effective path is invalid")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ResultProjectionError("effective path is unsafe")
    return path.as_posix()


def _project_operation(
    operation: OperationRequest,
    result: OperationResult,
    *,
    paths: AcquisitionPaths,
    run_id: str,
    processing_id: str,
    source_sha256: str,
    source_size: int,
) -> ProjectedOperation:
    if result.operation_id != operation.operation_id:
        raise ResultProjectionError("operation result identity differs from request")
    if result.status not in _TERMINAL_STATUSES:
        raise ResultProjectionError("operation result is not terminal")
    if not is_sha256_hex_digest(result.operation_fingerprint):
        raise ResultProjectionError("operation fingerprint is invalid")
    if not operation.requested and result.status != "not_requested":
        raise ResultProjectionError("unrequested operation has an execution result")
    if operation.requested and result.status == "not_requested":
        raise ResultProjectionError("requested operation is marked not requested")
    if operation.requested and operation.support_status == "unsupported":
        if result.status != "unsupported":
            raise ResultProjectionError(
                "unsupported request has a different result status"
            )
    if operation.requested and operation.support_status == "not_evaluated":
        if result.status != "blocked":
            raise ResultProjectionError("unevaluated request is not blocked")
    if any(
        not isinstance(item.code, str)
        or not item.code
        or not isinstance(item.detail, str)
        for item in result.diagnostics
    ):
        raise ResultProjectionError("operation diagnostic is invalid")
    if result.status in {"failed", "blocked", "unsupported"} and not result.diagnostics:
        raise ResultProjectionError("non-available operation lacks a diagnostic")
    output_path = None
    if result.status == "available":
        if (
            result.representation_id is None
            or not is_sha256_hex_digest(result.output_sha256 or "")
            or result.output_size is None
            or result.output_size < 0
            or result.staged_output is None
        ):
            raise ResultProjectionError("available operation lacks output identity")
        if (
            result.staged_output.output_sha256 != result.output_sha256
            or result.staged_output.output_size != result.output_size
        ):
            raise ResultProjectionError("staged output differs from operation result")
        if (
            not isinstance(result.staged_output.representation, str)
            or not result.staged_output.representation
        ):
            raise ResultProjectionError("staged output representation is invalid")
        if operation.operation == "raw" and (
            result.staged_output.representation != "raw"
            or result.output_sha256 != source_sha256
            or result.output_size != source_size
        ):
            raise ResultProjectionError("raw result is not an identity representation")
        if (
            operation.operation == "render_to_txt"
            and result.handler_id == "text_passthrough"
            and (
                result.staged_output.representation != "text_verbatim"
                or result.output_sha256 != source_sha256
                or result.output_size != source_size
            )
        ):
            raise ResultProjectionError("text passthrough differs from source identity")
        output_path = _verify_staged_output(
            result.staged_output,
            paths=paths,
            run_id=run_id,
            processing_id=processing_id,
        )
    elif any(
        value is not None
        for value in (
            result.representation_id,
            result.output_sha256,
            result.output_size,
            result.staged_output,
        )
    ):
        raise ResultProjectionError("non-available operation claims an output")
    return ProjectedOperation(
        operation_id=result.operation_id,
        status=result.status,
        operation_fingerprint=result.operation_fingerprint,
        representation_id=result.representation_id,
        output_sha256=result.output_sha256,
        output_size=result.output_size,
        handler_id=result.handler_id,
        handler_version=result.handler_version,
        diagnostics=result.diagnostics,
        staged_output_representation=(
            result.staged_output.representation if result.staged_output else None
        ),
        staged_output_path=output_path,
    )


def _project_target(
    request: ProcessingRequest,
    result: ProcessingResult,
    *,
    paths: AcquisitionPaths,
    run_id: str,
) -> ProjectedTarget:
    if result.target_id != request.target_id:
        raise ResultProjectionError("processing result target differs from request")
    if not is_sha256_hex_digest(result.source_sha256):
        raise ResultProjectionError("processing source digest is invalid")
    if result.source_sha256 != request.body.sha256:
        raise ResultProjectionError("processing result source differs from staged body")
    if not is_sha256_hex_digest(request.body.source_response_sha256):
        raise ResultProjectionError("source response digest is invalid")
    try:
        validate_safe_id(result.source_asset_id, "source_asset_id")
    except ValueError as error:
        raise ResultProjectionError("source asset ID is invalid") from error
    if not isinstance(result.route, DocumentRoute):
        raise ResultProjectionError("processing route is invalid")
    effective_path = _effective_path(result.effective_path)
    operations = {item.operation_id: item for item in result.operation_results}
    if len(operations) != len(result.operation_results):
        raise ResultProjectionError("operation result ID is duplicated")
    expected_operations = {item.operation_id: item for item in request.operations}
    if operations.keys() != expected_operations.keys():
        raise ResultProjectionError("operation result set is incomplete or unexpected")
    projected_operations = tuple(
        _project_operation(
            expected_operations[operation_id],
            operations[operation_id],
            paths=paths,
            run_id=run_id,
            processing_id=result.processing_id,
            source_sha256=request.body.sha256,
            source_size=request.body.byte_size,
        )
        for operation_id in sorted(operations)
    )
    verified = get_staged_body_ref(paths, run_id, request.target_id)
    if verified != request.body:
        raise ResultProjectionError("processing request body differs from S9 handoff")
    if request.selected_filename != verified.selected_filename:
        raise ResultProjectionError("selected filename differs from S9 handoff")
    source_path = _relative_staging_path(verified.path, paths, run_id)
    return ProjectedTarget(
        target_id=request.target_id,
        accession=str(request.accession),
        form=request.form,
        target_role=request.target_role,
        target_type=request.target_type,
        source_origin=request.source_origin,
        document_path=request.document_path,
        selected_filename=request.selected_filename,
        source_sha256=result.source_sha256,
        source_response_sha256=verified.source_response_sha256,
        source_size=verified.byte_size,
        source_asset_id=result.source_asset_id,
        source_staged_path=source_path,
        route=result.route,
        effective_path=effective_path,
        processing_id=result.processing_id,
        operations=projected_operations,
    )


def _fingerprint_targets(run_id: str, targets: tuple[ProjectedTarget, ...]) -> str:
    return canonical_hash(
        {
            "run_id": run_id,
            "targets": [
                {
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
                for target in targets
            ],
        }
    )


def project_terminal_results(
    requests: tuple[ProcessingRequest, ...],
    results: tuple[ProcessingResult, ...],
    *,
    paths: AcquisitionPaths,
    run_id: str,
) -> ProcessingResultProjection:
    """Project an explicit acquired-target request/result set without worker checks."""
    try:
        validate_safe_id(run_id, "run_id")
        requested = _request_index(requests, run_id)
        produced = _result_index(results)
        if requested.keys() != produced.keys():
            raise ResultProjectionError(
                "terminal processing result coverage is incomplete"
            )
        work_targets = _work_targets(paths, run_id, requested)
        projected = []
        for target_id in sorted(requested):
            request = requested[target_id]
            result = produced[target_id]
            _validate_work_target(request, work_targets[target_id])
            projected.append(
                _project_target(request, result, paths=paths, run_id=run_id)
            )
        targets = tuple(projected)
        return ProcessingResultProjection(
            run_id=run_id,
            fingerprint=_fingerprint_targets(run_id, targets),
            targets=targets,
        )
    except ResultProjectionError:
        raise
    except (
        BodyHandoffError,
        OSError,
        TypeError,
        ValueError,
        sqlite3.Error,
        pa.ArrowException,
    ) as error:
        raise ResultProjectionError(
            "terminal processing results failed validation"
        ) from error


__all__ = [
    "ProcessingResultProjection",
    "ProjectedOperation",
    "ProjectedTarget",
    "ResultProjectionError",
    "project_terminal_results",
]
