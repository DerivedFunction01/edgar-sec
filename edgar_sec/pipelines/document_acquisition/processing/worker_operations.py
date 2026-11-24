from __future__ import annotations

import hashlib

from edgar_sec.domain.document.path_facts import DocumentPathFacts
from edgar_sec.domain.document.route import DocumentRoute
from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    allowed_operations_of,
)
from edgar_sec.engine.document_processing.acquisition_capabilities import (
    resolve_acquisition_capability,
)
from edgar_sec.domain.forms.families.processing_profiles import get_family_profile
from edgar_sec.engine.document_processing.processor import (
    AcquisitionProcessRequest,
    AcquisitionProcessor,
    InputRecord,
    OperationRecord,
)
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.foundation.runtime.paths import validate_safe_id
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths
from edgar_sec.pipelines.document_acquisition.processing.errors import (
    ProcessingError,
)
from edgar_sec.pipelines.document_acquisition.processing.models import (
    OperationRequest,
    OperationResult,
    ProcessingDiagnostic,
    ProcessingRequest,
    StagedOutputRef,
)
from edgar_sec.pipelines.document_acquisition.processing.io import (
    ProcessingIOError,
    operation_fingerprint,
    operation_pins,
    stage_derived_output,
)
from edgar_sec.pipelines.document_acquisition.schemas import StagedBodyRef


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
    allowed = allowed_operations_of(profile)
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
