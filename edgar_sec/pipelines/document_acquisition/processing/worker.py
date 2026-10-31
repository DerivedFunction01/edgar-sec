from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime

import pyarrow as pa

from edgar_sec.domain.document.path_facts import DocumentPathFacts
from edgar_sec.domain.document.route import (
    DocumentRoute,
    content_route,
    document_route,
)
from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DEFAULT_OPERATIONS,
)
from edgar_sec.engine.document_processing.acquisition_capabilities import (
    resolve_acquisition_capability,
)
from edgar_sec.domain.forms.families.processing_profiles import get_family_profile
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.domain.sec_urls import validate_archive_url
from edgar_sec.engine.document_processing.processor import (
    AcquisitionProcessRequest,
    AcquisitionProcessor,
    InputRecord,
    OperationRecord,
)
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
from edgar_sec.pipelines.document_acquisition.processing.models import (
    OperationRequest,
    OperationResult,
    ProcessingDiagnostic,
    ProcessingRequest,
    ProcessingResult,
    StagedOutputRef,
)
from edgar_sec.pipelines.document_acquisition.processing.assessment import (
    assess_exhibit_processing,
)
from edgar_sec.pipelines.document_acquisition.processing.io import (
    ProcessingIOError,
    operation_fingerprint,
    operation_pins,
    read_bounded_source,
    select_operation_execution,
    stage_derived_output,
    validate_prior_operation_result,
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


def _validate_mandatory_raw(
    request: ProcessingRequest, facts: DocumentPathFacts
) -> OperationRequest:
    raw_operations = [item for item in request.operations if item.operation == "raw"]
    if (
        len(raw_operations) != 1
        or not raw_operations[0].requested
        or raw_operations[0].support_status != "supported"
        or not (raw_operations[0].source_request_id or "").strip()
        or operation_pins(raw_operations[0])
        != resolve_acquisition_capability(
            request.form,
            request.target_role,
            raw_operations[0].operation,
            facts,
        ).pins
    ):
        raise ProcessingError("matched acquired target lacks mandatory pinned raw")
    return raw_operations[0]


def _operation_results(
    request: ProcessingRequest,
    paths: AcquisitionPaths,
    route: DocumentRoute,
    effective_path: str,
    path_facts: DocumentPathFacts,
    body: StagedBodyRef,
    source: bytes | None,
    processing_id: str,
    prior_by_id: dict[str, OperationResult],
    selected_ids: frozenset[str],
) -> tuple[OperationResult, ...]:
    results = []
    seen: set[str] = set()
    for operation in request.operations:
        _validate_operation(operation)
        if operation.operation_id in seen:
            raise ProcessingError("operation IDs are not unique")
        seen.add(operation.operation_id)
        prior = prior_by_id.get(operation.operation_id)
        if prior is not None:
            results.append(prior)
            continue
        fingerprint = operation_fingerprint(
            request, operation, body, route, effective_path
        )
        status = "failed"
        code = "capability_pin_mismatch"
        detail = "The pinned operation does not match the effective document route."
        representation = None
        staged_output = None
        output_sha256 = None
        output_size = None
        handler_id = None
        handler_version = None
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
        elif (
            operation.requested
            and operation.support_status == "supported"
            and operation.operation_id not in selected_ids
        ):
            raise ProcessingError("requested operation is neither selected nor reused")
        elif operation.operation == "raw":
            status = "available"
            code = detail = ""
            representation = "raw"
            output_sha256 = body.sha256
            output_size = body.byte_size
            handler_id = operation.handler_id
            handler_version = operation.handler_version
            staged_output = StagedOutputRef(
                staging_id=processing_id,
                path=body.path,
                representation="raw",
                output_sha256=body.sha256,
                output_size=body.byte_size,
            )
        elif not (operation.source_request_id or "").strip():
            status = "failed"
            code = "source_request_missing"
            detail = "The supported operation has no pinned source request."
        else:
            expected = resolve_acquisition_capability(
                request.form,
                request.target_role,
                operation.operation,
                path_facts,
                route,
            ).pins
            if expected is None:
                status = "unsupported"
                code = "route_unsupported"
                detail = "No registered handler admits this effective document route."
            elif operation_pins(operation) != expected:
                status = "failed"
            elif source is None:
                status = "failed"
                code = "source_unavailable"
                detail = "Source bytes are not available for processing."
            else:
                processor = AcquisitionProcessor()
                engine_result = processor.process(
                    AcquisitionProcessRequest(
                        target_id=request.target_id,
                        family=resolve_alias(request.form) or request.form,
                        form_type=request.form,
                        role=request.target_role,
                        target_type=request.target_type,
                        filing_date=request.filing_date,
                        report_date=request.report_date,
                        path_facts=path_facts,
                        operations=(
                            OperationRecord(
                                capability_version=operation.capability_version or "",
                                output_kind=operation.output_kind or "",
                                source_ids=(operation.source_request_id,),
                                operation=operation.operation,
                                handler_id=operation.handler_id,
                                handler_version=operation.handler_version,
                            ),
                        ),
                        inputs=(
                            InputRecord(
                                source_id=operation.source_request_id,
                                locator_provenance=operation.source_request_id or "",
                                selected_path=effective_path,
                                path_facts=path_facts,
                                sha256=body.sha256,
                                byte_size=body.byte_size,
                                raw_bytes=source,
                            ),
                        ),
                    )
                )
                outcome = engine_result.outcomes[0]
                if outcome.status == "ok":
                    output = outcome.output_bytes
                    if (
                        output is None
                        or outcome.output_sha256 is None
                        or outcome.output_byte_size != len(output)
                        or hashlib.sha256(output).hexdigest() != outcome.output_sha256
                    ):
                        status = "failed"
                        code = "output_identity_mismatch"
                        detail = "The engine output failed digest or size validation."
                    else:
                        try:
                            staged_output = stage_derived_output(
                                paths=paths,
                                run_id=body.run_id,
                                processing_id=processing_id,
                                operation_id=canonical_hash(operation.operation_id)[
                                    :24
                                ],
                                representation="text_normalized"
                                if outcome.output_kind == "text"
                                else "xml",
                                output=output,
                                expected_sha256=outcome.output_sha256,
                                expected_size=outcome.output_byte_size
                                if outcome.output_byte_size is not None
                                else -1,
                            )
                        except (OSError, ProcessingIOError, ValueError):
                            status = "failed"
                            code = "output_staging_failed"
                            detail = (
                                "The derived output could not be staged and verified."
                            )
                        else:
                            status = "available"
                            code = detail = ""
                            representation = staged_output.representation
                            output_sha256 = outcome.output_sha256
                            output_size = outcome.output_byte_size
                            handler_id = outcome.handler_id
                            handler_version = outcome.handler_version
                else:
                    status = "failed" if outcome.status == "failed" else "unsupported"
                    code = outcome.error or "handler_unavailable"
                    detail = "The engine did not produce an admitted operation output."
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
                output_sha256=output_sha256,
                output_size=output_size,
                handler_id=handler_id,
                handler_version=handler_version,
                diagnostics=diagnostics,
                staged_output=staged_output,
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
        operation_kind = AcquisitionOperation(operation.operation)
        role_allowed = request.target_role == "exhibit" and operation_kind is (
            AcquisitionOperation.RENDER_TO_TXT
        )
        if request.target_role == "exhibit" and operation_kind is (
            AcquisitionOperation.RENDER_TO_XML
        ):
            role_allowed = False
        if (
            operation.requested
            and operation.support_status == "supported"
            and operation_kind not in allowed
            and not role_allowed
        ):
            raise ProcessingError(
                "requested operation is not allowed by the form-family profile"
            )


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


__all__ = ["ProcessingError", "process_target"]
