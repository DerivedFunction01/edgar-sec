from __future__ import annotations

import hashlib
import os
import sqlite3
import stat
from datetime import UTC, datetime

import pyarrow as pa

from edgar_sec.domain.document.route import DocumentRoute, document_route
from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DEFAULT_OPERATIONS,
)
from edgar_sec.domain.forms.families.processing_profiles import get_family_profile
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.domain.sec_urls import validate_archive_url
from edgar_sec.foundation.hashing import is_sha256_hex_digest
from edgar_sec.foundation.io import DEFAULT_IO_CHUNK_SIZE
from edgar_sec.foundation.runtime.paths import validate_safe_id
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.pipelines.document_acquisition.body_handoff import (
    BodyHandoffError,
    get_staged_body_ref,
    read_body_consumption_receipt,
    record_body_consumption_receipt,
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
from edgar_sec.pipelines.document_acquisition.run_state.evidence import (
    get_attempt_evidence_group,
    list_target_attempts,
)
from edgar_sec.pipelines.document_acquisition.run_state.store import (
    get_attempt,
    get_target_state,
)
from edgar_sec.pipelines.document_acquisition.run_validation import (
    iter_work_order_rows,
    load_validated_work_order,
)
from edgar_sec.pipelines.document_acquisition.schemas import (
    RECEIPT_SCHEMA_VERSION,
    StagedBodyRef,
)


class ProcessingError(ValueError):
    pass


def _target_row(
    paths: AcquisitionPaths, request: ProcessingRequest
) -> dict[str, object]:
    try:
        parts = load_validated_work_order(paths, request.body.run_id)
        rows = (
            row
            for row in iter_work_order_rows(parts)
            if row.get("target_id") == request.target_id
        )
        row = next(rows)
        if next(rows, None) is not None:
            raise ProcessingError("target ID is duplicated in the work order")
    except StopIteration as error:
        raise ProcessingError("target ID is not in the run work order") from error
    except ProcessingError:
        raise
    except (OSError, ValueError, TypeError, sqlite3.Error, pa.ArrowException) as error:
        raise ProcessingError("acquisition work order failed validation") from error

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
        raise ProcessingError("processing request identity differs from work order")
    if row["retrieval_mode"] not in {"direct_url", "bundle_sequence"}:
        raise ProcessingError("work-order retrieval mode is not processable")
    try:
        source_parts = validate_archive_url(str(row["target_url"]), accession)
    except ValueError as error:
        raise ProcessingError("work-order target URL is invalid") from error
    if request.document_path != source_parts.document_path:
        raise ProcessingError("processing request path differs from work order")
    if request.body.target_id != request.target_id:
        raise ProcessingError("staged body target identity differs from request")
    return row


def _effective_route(
    paths: AcquisitionPaths,
    request: ProcessingRequest,
    row: dict[str, object],
) -> tuple[DocumentRoute, str]:
    if row["retrieval_mode"] == "bundle_sequence":
        raise ProcessingError(
            "bundle child filename is absent from the committed S9 handoff"
        )
    if request.selected_filename is not None:
        raise ProcessingError("direct targets cannot supply a bundle filename")

    try:
        database_path = paths.run_state_path(request.body.run_id)
        state = get_target_state(database_path, request.target_id)
        attempts = list_target_attempts(database_path, request.target_id)
    except (OSError, ValueError, sqlite3.Error) as error:
        raise ProcessingError("selected target evidence is invalid") from error
    if state is None or state.outcome != "acquired" or state.last_attempt_id is None:
        raise ProcessingError("acquired target has no selected attempt")
    selected_attempt = get_attempt(
        database_path, request.target_id, state.last_attempt_id
    )
    initial = next(
        (
            attempt
            for attempt in attempts
            if attempt.attempt_kind == "document_body" and attempt.attempt_number == 1
        ),
        None,
    )
    if (
        initial is None
        or initial.requested_url != row["target_url"]
        or selected_attempt is None
        or selected_attempt.attempt_kind != "document_body"
        or selected_attempt.selected_sha256 != request.body.sha256
        or selected_attempt.selected_byte_size != request.body.byte_size
    ):
        raise ProcessingError("acquired attempt differs from work order or body")

    resolution = None
    for attempt in attempts:
        if attempt.attempt_kind != "document_body":
            continue
        try:
            evidence = get_attempt_evidence_group(
                database_path, request.target_id, attempt.attempt_id
            )
        except (OSError, ValueError, sqlite3.Error) as error:
            raise ProcessingError("selected target evidence is invalid") from error
        if (
            evidence is not None
            and evidence.selected_body_attempt is not None
            and evidence.selected_body_attempt.attempt_id == state.last_attempt_id
        ):
            resolution = evidence.resolution
            break

    if resolution is not None and resolution.selected_url is not None:
        if resolution.result not in {"accepted_sequence_1", "recovered"}:
            raise ProcessingError("selected target resolution is not successful")
        if resolution.selected_retrieval_mode == "bundle_sequence":
            raise ProcessingError(
                "bundle child filename is absent from the committed S9 handoff"
            )
        if (
            resolution.selected_retrieval_mode != "direct_url"
            or selected_attempt.requested_url != resolution.selected_url
        ):
            raise ProcessingError("selected target route is unresolved")
        route_url = resolution.selected_url
    else:
        if selected_attempt.requested_url != row["target_url"]:
            raise ProcessingError("acquired attempt URL differs from work order")
        route_url = str(row["target_url"])
    try:
        selected = validate_archive_url(route_url, request.accession)
        if selected_attempt.final_url is not None:
            validate_archive_url(selected_attempt.final_url, request.accession)
    except ValueError as error:
        raise ProcessingError("selected route URL is invalid") from error
    return document_route(selected.document_path), selected.document_path


def _verify_body(ref: StagedBodyRef) -> tuple[str, int]:
    path = ref.path
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise ProcessingError("selected body is unavailable") from error
    digest = hashlib.sha256()
    size = 0
    try:
        file_stat = os.fstat(descriptor)
        if not stat.S_ISREG(file_stat.st_mode):
            raise ProcessingError("selected body is not a regular file")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            while chunk := stream.read(DEFAULT_IO_CHUNK_SIZE):
                digest.update(chunk)
                size += len(chunk)
    finally:
        os.close(descriptor)
    observed = digest.hexdigest(), size
    if observed != (ref.sha256, ref.byte_size):
        raise ProcessingError("selected body failed digest or size validation")
    return observed


def _operation_results(
    request: ProcessingRequest,
    route: DocumentRoute,
    effective_path: str,
    body: StagedBodyRef,
    processing_id: str,
) -> tuple[OperationResult, ...]:
    results = []
    seen: set[str] = set()
    for operation in request.operations:
        _validate_operation(operation)
        if operation.operation_id in seen:
            raise ProcessingError("operation IDs are not unique")
        seen.add(operation.operation_id)
        fingerprint = canonical_hash(
            {
                "operation_id": operation.operation_id,
                "operation": operation.operation,
                "requested": operation.requested,
                "support_status": operation.support_status,
                "source_request_id": operation.source_request_id,
                "capability_id": operation.capability_id,
                "capability_version": operation.capability_version,
                "handler_id": operation.handler_id,
                "handler_version": operation.handler_version,
                "output_kind": operation.output_kind,
                "target_id": request.target_id,
                "accession": str(request.accession),
                "form": request.form,
                "target_role": request.target_role,
                "target_type": request.target_type,
                "document_path": request.document_path,
                "selected_filename": request.selected_filename,
                "source_origin": request.source_origin,
                "source_sha256": body.sha256,
                "effective_path": effective_path,
                "route": route.value,
            }
        )
        status = "failed"
        code = "handler_unavailable"
        detail = "No executable export handler is registered for this operation."
        representation = None
        output = None
        handler_id = operation.handler_id
        handler_version = operation.handler_version
        if not operation.requested:
            status = "not_requested"
            code = detail = ""
        elif operation.support_status == "unsupported":
            status = "unsupported"
            code = "capability_unsupported"
            detail = "The pinned operation is unsupported for this target."
        elif operation.support_status == "not_evaluated":
            status = "blocked"
            code = "capability_not_evaluated"
            detail = "The pinned operation has no evaluated capability."
        elif operation.operation == "raw":
            status = "available"
            code = detail = ""
            handler_id = "raw_identity"
            handler_version = "1"
            representation = "raw"
            output = StagedOutputRef(
                staging_id=processing_id,
                path=body.path,
                representation="raw",
                output_sha256=body.sha256,
                output_size=body.byte_size,
            )
        elif (
            operation.operation == "render_to_txt"
            and route is DocumentRoute.TEXT
            and operation.handler_id == "text_passthrough"
            and operation.handler_version == "1"
        ):
            status = "available"
            code = detail = ""
            handler_id = "text_passthrough"
            handler_version = "1"
            representation = "text_verbatim"
            output = StagedOutputRef(
                staging_id=processing_id,
                path=body.path,
                representation="text_verbatim",
                output_sha256=body.sha256,
                output_size=body.byte_size,
            )
        elif operation.operation == "render_to_txt" and route in {
            DocumentRoute.PAPER,
            DocumentRoute.BINARY,
            DocumentRoute.XML,
            DocumentRoute.UNKNOWN,
        }:
            status = "unsupported"
            code = "route_unsupported"
            detail = "This document route has no approved text export."
        diagnostics = (ProcessingDiagnostic(code, detail),) if code else ()
        representation_id = (
            f"rep_{canonical_hash([fingerprint, representation])[:32]}"
            if representation is not None
            else None
        )
        results.append(
            OperationResult(
                operation_id=operation.operation_id,
                operation_fingerprint=fingerprint,
                status=status,
                representation_id=representation_id,
                output_sha256=output.output_sha256 if output else None,
                output_size=output.output_size if output else None,
                handler_id=handler_id,
                handler_version=handler_version,
                diagnostics=diagnostics,
                staged_output=output,
            )
        )
    return tuple(results)


def _validate_operation(operation: OperationRequest) -> None:
    try:
        validate_safe_id(operation.operation_id, "operation_id")
    except ValueError as error:
        raise ProcessingError("operation ID is invalid") from error
    if operation.operation not in {"raw", "render_to_txt", "render_to_xml"}:
        raise ProcessingError("operation name is invalid")
    if type(operation.requested) is not bool:
        raise ProcessingError("operation requested flag must be boolean")
    if operation.support_status not in {"supported", "unsupported", "not_evaluated"}:
        raise ProcessingError("operation support status is invalid")


def _validate_operations(operations: tuple[OperationRequest, ...]) -> None:
    seen: set[str] = set()
    for operation in operations:
        _validate_operation(operation)
        if operation.operation_id in seen:
            raise ProcessingError("operation IDs are not unique")
        seen.add(operation.operation_id)


def _validate_family_operations(request: ProcessingRequest) -> None:
    profile = get_family_profile(request.form)
    allowed = profile.allowed_operations if profile is not None else DEFAULT_OPERATIONS
    for operation in request.operations:
        if (
            operation.requested
            and operation.support_status == "supported"
            and AcquisitionOperation(operation.operation) not in allowed
        ):
            raise ProcessingError(
                "requested operation is not allowed by the form-family profile"
            )


def _processing_id(
    request: ProcessingRequest, route: DocumentRoute, effective_path: str
) -> str:
    return (
        "proc_"
        + canonical_hash(
            {
                "run_id": request.body.run_id,
                "target_id": request.target_id,
                "accession": str(request.accession),
                "form": request.form,
                "target_role": request.target_role,
                "target_type": request.target_type,
                "document_path": request.document_path,
                "selected_filename": request.selected_filename,
                "source_origin": request.source_origin,
                "body_sha256": request.body.sha256,
                "source_response_sha256": request.body.source_response_sha256,
                "body_size": request.body.byte_size,
                "effective_path": effective_path,
                "route": route.value,
                "operations": [
                    {
                        "operation_id": operation.operation_id,
                        "operation": operation.operation,
                        "requested": operation.requested,
                        "support_status": operation.support_status,
                        "source_request_id": operation.source_request_id,
                        "capability_id": operation.capability_id,
                        "capability_version": operation.capability_version,
                        "handler_id": operation.handler_id,
                        "handler_version": operation.handler_version,
                        "output_kind": operation.output_kind,
                    }
                    for operation in request.operations
                ],
            }
        )[:36]
    )


def _record_receipt(
    paths: AcquisitionPaths, body: StagedBodyRef, processing_id: str
) -> None:
    prior = read_body_consumption_receipt(paths, body.run_id, body.target_id)
    if prior is not None:
        if prior["processing_run_id"] != processing_id:
            raise ProcessingError(
                "body already has a receipt for another processing run"
            )
        return
    record_body_consumption_receipt(
        paths,
        {
            "receipt_schema_version": RECEIPT_SCHEMA_VERSION,
            "run_id": body.run_id,
            "target_id": body.target_id,
            "source_response_sha256": body.source_response_sha256,
            "selected_sha256": body.sha256,
            "processing_run_id": processing_id,
            "consumed_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        },
    )


def process_target(
    request: ProcessingRequest,
    *,
    paths: AcquisitionPaths,
) -> ProcessingResult:
    try:
        validate_safe_id(request.target_id, "target_id")
        _validate_operations(request.operations)
        _validate_family_operations(request)
        row = _target_row(paths, request)
        route, effective_path = _effective_route(paths, request, row)
        verified_body = get_staged_body_ref(
            paths, request.body.run_id, request.target_id
        )
        if request.body != verified_body:
            raise ProcessingError(
                "staged body reference differs from committed identity"
            )
        source_sha256, source_size = _verify_body(verified_body)
        if source_size != verified_body.byte_size or not is_sha256_hex_digest(
            source_sha256
        ):
            raise ProcessingError("selected body identity is invalid")
        source_asset_id = (
            "asset_"
            + canonical_hash(
                [request.target_id, source_sha256, verified_body.source_response_sha256]
            )[:32]
        )
        processing_id = _processing_id(request, route, effective_path)
        operation_results = _operation_results(
            request, route, effective_path, verified_body, processing_id
        )
        _record_receipt(paths, verified_body, processing_id)
    except ProcessingError:
        raise
    except (
        BodyHandoffError,
        OSError,
        TypeError,
        ValueError,
        sqlite3.Error,
        pa.ArrowException,
    ) as error:
        raise ProcessingError("target processing failed validation") from error
    return ProcessingResult(
        processing_id=processing_id,
        target_id=request.target_id,
        source_sha256=source_sha256,
        source_asset_id=source_asset_id,
        route=route,
        effective_path=effective_path,
        operation_results=operation_results,
    )


__all__ = ["ProcessingError", "process_target"]
