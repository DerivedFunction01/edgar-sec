from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pyarrow as pa

from edgar_sec.domain.document.path_facts import DocumentPathFacts
from edgar_sec.domain.document.route import (
    DocumentRoute,
    content_route,
    document_route,
)
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.domain.sec_urls import validate_archive_url
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.foundation.hashing import is_sha256_hex_digest
from edgar_sec.foundation.runtime.paths import validate_safe_id
from edgar_sec.pipelines.document_acquisition.body_handoff import (
    BodyHandoffError,
    get_staged_body_ref,
    get_staged_body_metadata_ref,
    read_body_consumption_receipt,
    record_body_consumption_receipt,
)
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths
from edgar_sec.pipelines.document_acquisition.processing.errors import (
    ProcessingError,
)
from edgar_sec.pipelines.document_acquisition.processing.models import (
    OperationResult,
    ProcessingRequest,
    ProcessingResult,
)
from edgar_sec.pipelines.document_acquisition.processing.assessment import (
    assess_exhibit_processing,
)
from edgar_sec.pipelines.document_acquisition.processing.io import (
    ProcessingIOError,
    operation_fingerprint,
    read_bounded_source,
    select_operation_execution,
    validate_prior_operation_result,
)
from edgar_sec.pipelines.document_acquisition.processing.worker_operations import (
    _operation_results,
    _validate_family_operations,
    _validate_mandatory_raw,
    _validate_operations,
)
from edgar_sec.pipelines.document_acquisition.run_state.evidence import (
    get_attempt_evidence_group,
    list_target_attempts,
)
from edgar_sec.pipelines.document_acquisition.run_state.queries import (
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
    validate_selected_filename,
)


_NO_RECEIPT_DIAGNOSTICS = frozenset(
    {
        "invalid_source_bytes",
        "invalid_source_size",
        "source_size_mismatch",
        "source_digest_mismatch",
        "invalid_source_count",
        "missing_or_ambiguous_source",
    }
)


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
        or row["filing_date"] != request.filing_date
        or row["report_date"] != request.report_date
        or row["target_role"] != request.target_role
        or row["target_type"] != request.target_type
        or row["source_origin"] != request.source_origin
        or row["executable"] is not True
        or row["status"] != "matched"
    ):
        raise ProcessingError("processing request identity differs from work order")
    if row["retrieval_mode"] not in {"direct_url", "bundle_sequence", "bundle_scan"}:
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
    body: StagedBodyRef,
) -> tuple[DocumentRoute, str]:
    if (
        row["retrieval_mode"] in {"bundle_sequence", "bundle_scan"}
        and request.selected_filename is None
    ):
        raise ProcessingError("bundle child filename is absent from handoff")
    try:
        requested_filename = validate_selected_filename(request.selected_filename)
        committed_filename = validate_selected_filename(body.selected_filename)
        database_path = paths.run_state_path(request.body.run_id)
        state = get_target_state(database_path, request.target_id)
        attempts = list_target_attempts(database_path, request.target_id)
    except (OSError, ValueError, sqlite3.Error) as error:
        raise ProcessingError("selected target evidence is invalid") from error
    if requested_filename != committed_filename:
        raise ProcessingError("selected filename differs from committed handoff")
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
        or state.selected_sha256 != body.sha256
        or state.selected_byte_size != body.byte_size
        or state.source_sha256 != body.source_response_sha256
        or state.source_byte_size != body.source_response_byte_size
        or selected_attempt.selected_sha256 != body.sha256
        or selected_attempt.selected_byte_size != body.byte_size
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

    retrieval_mode = str(row["retrieval_mode"])
    if resolution is not None and resolution.selected_url is not None:
        if resolution.result not in {
            "accepted_sequence_1",
            "recovered",
            "selected_in_bundle",
        }:
            raise ProcessingError("selected target resolution is not successful")
        if (
            resolution.selected_retrieval_mode
            not in {"direct_url", "bundle_sequence", "bundle_scan"}
            or selected_attempt.requested_url != resolution.selected_url
        ):
            raise ProcessingError("selected target route is unresolved")
        retrieval_mode = resolution.selected_retrieval_mode
        route_url = resolution.selected_url
    else:
        if selected_attempt.requested_url != row["target_url"]:
            raise ProcessingError("acquired attempt URL differs from work order")
        route_url = str(row["target_url"])
    if retrieval_mode == "direct_url" and committed_filename is not None:
        selected_basename = route_url.rsplit("/", 1)[-1]
        if resolution is None or committed_filename != selected_basename:
            raise ProcessingError("direct target has an unexpected selected filename")
    try:
        selected = validate_archive_url(route_url, request.accession)
        if selected_attempt.final_url is not None:
            validate_archive_url(selected_attempt.final_url, request.accession)
    except ValueError as error:
        raise ProcessingError("selected route URL is invalid") from error
    if (
        retrieval_mode in {"bundle_sequence", "bundle_scan"}
        or committed_filename is not None
    ):
        if committed_filename is None:
            raise ProcessingError("bundle child filename is absent from handoff")
        return content_route(committed_filename), committed_filename
    if retrieval_mode != "direct_url":
        raise ProcessingError("selected target retrieval mode is unresolved")
    return document_route(selected.document_path), selected.document_path


def _document_path_facts(
    request: ProcessingRequest, effective_path: str, route: DocumentRoute
) -> DocumentPathFacts:
    facts = (
        DocumentPathFacts.from_sgml_filename(effective_path)
        if request.selected_filename is not None
        else DocumentPathFacts.from_archive_path(effective_path)
    )
    route_from_facts = (
        content_route(facts.path_context)
        if request.selected_filename is not None
        else document_route(facts.path_context)
    )
    if (
        not facts.path_context
        or facts.path_context != effective_path
        or route_from_facts is not route
    ):
        raise ProcessingError("effective document path facts are inconsistent")
    return facts


def _processing_id(
    request: ProcessingRequest,
    route: DocumentRoute,
    effective_path: str,
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
                "body_path": request.body.path.as_posix(),
                "source_response_sha256": request.body.source_response_sha256,
                "source_response_byte_size": request.body.source_response_byte_size,
                "source_response_path": (
                    request.body.source_response_path.as_posix()
                    if request.body.source_response_path is not None
                    else None
                ),
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
    prior_results: tuple[OperationResult, ...] | None = None,
    selected_operation_ids: tuple[str, ...] | None = None,
) -> ProcessingResult:
    try:
        if not isinstance(request.body, StagedBodyRef):
            raise ProcessingError("production processing requires a staged run body")
        validate_safe_id(request.target_id, "target_id")
        _validate_operations(request.operations)
        _validate_family_operations(request)
        prior_by_id, selected_ids = select_operation_execution(
            request, prior_results, selected_operation_ids
        )
        row = _target_row(paths, request)
        if (
            not is_sha256_hex_digest(request.body.sha256)
            or type(request.body.byte_size) is not int
            or request.body.byte_size < 0
            or not is_sha256_hex_digest(request.body.source_response_sha256)
            or type(request.body.source_response_byte_size) is not int
            or request.body.source_response_byte_size < 0
        ):
            raise ProcessingError("staged body metadata is invalid")
        route, effective_path = _effective_route(paths, request, row, request.body)
        path_facts = _document_path_facts(request, effective_path, route)
        raw_operation = _validate_mandatory_raw(request, path_facts)
        processing_id = _processing_id(request, route, effective_path)
        source_sha256 = request.body.sha256
        source_asset_id = (
            "asset_"
            + canonical_hash(
                [request.target_id, source_sha256, request.body.source_response_sha256]
            )[:32]
        )
        metadata_body = get_staged_body_metadata_ref(
            paths, request.body.run_id, request.target_id
        )
        if request.body != metadata_body:
            raise ProcessingError(
                "staged body metadata differs from committed identity"
            )
        request_operations = {
            operation.operation_id: operation for operation in request.operations
        }
        for operation_id, prior in prior_by_id.items():
            operation = request_operations[operation_id]
            fingerprint = operation_fingerprint(
                request,
                operation,
                metadata_body,
                route,
                effective_path,
            )
            validate_prior_operation_result(
                paths,
                operation,
                prior,
                metadata_body,
                processing_id,
                fingerprint,
            )

        derived_selected = any(
            op.operation_id in selected_ids and op.operation != "raw"
            for op in request.operations
            if op.requested and op.support_status == "supported"
        )
        source = None
        body_consumed = False
        verified_body = metadata_body
        if derived_selected:
            source = read_bounded_source(
                verified_body.path,
                verified_body.byte_size,
            )
            body_consumed = True
        elif raw_operation.operation_id in selected_ids:
            verified_body = get_staged_body_ref(
                paths, request.body.run_id, request.target_id
            )
            if verified_body != metadata_body:
                raise ProcessingError(
                    "staged body reference differs from committed metadata"
                )
            body_consumed = True
        operation_results = _operation_results(
            request,
            paths,
            route,
            effective_path,
            path_facts,
            verified_body,
            source,
            processing_id,
            prior_by_id,
            selected_ids,
        )
        exhibit_assessment, assessment_fingerprint = assess_exhibit_processing(
            request, operation_results, route, effective_path
        )
        raw_result = next(
            item
            for item in operation_results
            if item.operation_id == raw_operation.operation_id
        )
        if (
            raw_result.status != "available"
            or raw_result.output_sha256 != verified_body.sha256
            or raw_result.output_size != verified_body.byte_size
            or raw_result.staged_output is None
            or raw_result.staged_output.path != verified_body.path
        ):
            raise ProcessingError(
                "mandatory raw operation did not preserve selected bytes"
            )
        receipt_refused = any(
            diagnostic.code in _NO_RECEIPT_DIAGNOSTICS
            for result in operation_results
            for diagnostic in result.diagnostics
        )
        if body_consumed and not receipt_refused:
            _record_receipt(paths, verified_body, processing_id)
    except ProcessingError:
        raise
    except (
        BodyHandoffError,
        ProcessingIOError,
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
        exhibit_assessment=exhibit_assessment,
        exhibit_assessment_fingerprint=assessment_fingerprint,
    )


__all__ = ["process_target"]
