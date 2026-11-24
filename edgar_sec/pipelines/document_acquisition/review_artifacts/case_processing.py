from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlsplit

from edgar_sec.domain.document.path_facts import DocumentPathFacts
from edgar_sec.domain.document.route import DocumentRoute, content_route, document_route
from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.domain.forms.common.processing import (
    allowed_operations_of,
    profile_version_of,
)
from edgar_sec.domain.forms.families.processing_profiles import get_family_profile
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.document_processing.acquisition_capabilities import (
    resolve_acquisition_capability,
)
from edgar_sec.engine.document_processing.capabilities import operation_output_kind
from edgar_sec.engine.forms.common.xml.unparsed import (
    UNPARSED_SECTIONS_FILE,
    serialize_unparsed_sections,
)
from edgar_sec.engine.document_processing.processor import (
    AcquisitionProcessRequest,
    AcquisitionProcessor,
    InputRecord,
    OperationRecord,
)
from edgar_sec.foundation.hashing import file_sha256, sha256_bytes, sha256_text
from edgar_sec.foundation.runtime.paths import validate_safe_id
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.storage.atomic import atomic_write_bytes
from edgar_sec.pipelines.document_acquisition.fixture_store.discovery import (
    FixtureCaseMetadata,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.reader import (
    _materialize_fixture_case,
    verify_fixture_lazy_index,
)
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths
from edgar_sec.pipelines.document_acquisition.processing.assessment import (
    assess_exhibit_processing,
)
from edgar_sec.pipelines.document_acquisition.processing.models import (
    OperationRequest,
    OperationResult,
    ProcessingDiagnostic,
    ProcessingRequest,
    StagedOutputRef,
)
from edgar_sec.pipelines.document_acquisition.review_artifacts.errors import (
    ProcessingReviewError,
)
from edgar_sec.pipelines.document_acquisition.schemas import FixtureBodyRef


_OPERATIONS = ("raw", "render_to_txt", "render_to_xml")


def _case_id(case: FixtureCaseMetadata) -> str:
    digest = sha256_text(f"{case.fixture_id}\n{case.capture_id}\n{case.target_id}")[:20]
    return validate_safe_id(f"{case.accession}--{digest}", "review_case_id")


def _validated_fixture_body(
    case: FixtureCaseMetadata, paths: AcquisitionPaths, destination: Path
) -> bytes:
    if case.index_sha256 is not None:
        verify_fixture_lazy_index(
            paths, case.fixture_id, case.accession, case.index_sha256
        )
    materialized = _materialize_fixture_case(
        case.fixture_id,
        case.capture_id,
        case.target_id,
        destination,
        paths=paths,
    )
    if (
        materialized.body_sha256 != case.body_sha256
        or materialized.byte_size != case.byte_size
        or file_sha256(destination) != case.body_sha256
    ):
        raise ProcessingReviewError("fixture body differs from selected identity")
    return destination.read_bytes()


def _input_path(case: FixtureCaseMetadata) -> tuple[str, str, DocumentPathFacts]:
    if case.selected_filename is not None:
        selected_path = case.selected_filename
        facts = DocumentPathFacts.from_sgml_filename(selected_path)
        route = content_route(selected_path)
    else:
        if case.target_url is None:
            raise ProcessingReviewError("fixture case has no selected document path")
        selected_path = urlsplit(case.target_url).path
        facts = DocumentPathFacts.from_archive_path(selected_path)
        route = document_route(selected_path)
    if not facts.path_context or not selected_path:
        raise ProcessingReviewError("fixture case has no selected document path")
    return selected_path, route.value, facts


def _operation_requests(
    case: FixtureCaseMetadata,
    facts: DocumentPathFacts,
    route: DocumentRoute,
) -> tuple[OperationRequest, ...]:
    family = resolve_alias(case.form) or case.form.strip().upper()
    requests = []
    for operation in _OPERATIONS:
        capability = resolve_acquisition_capability(
            family, case.target_role, operation, facts, route
        )
        output_kind = operation_output_kind(operation)
        if output_kind is None:
            raise ProcessingReviewError("processing operation is unsupported")
        operation_id = (
            "op_"
            + canonical_hash(
                {
                    "fixture": case.fixture_id,
                    "capture": case.capture_id,
                    "target": case.target_id,
                    "operation": operation,
                }
            )[:24]
        )
        requests.append(
            OperationRequest(
                operation_id=operation_id,
                operation=operation,
                requested=True,
                support_status="supported"
                if capability.pins is not None
                else "unsupported",
                source_request_id=case.request_id,
                capability_id=capability.capability_id,
                capability_version=capability.capability_version,
                handler_id=capability.handler_id,
                handler_version=capability.handler_version,
                output_kind=capability.output_kind,
            )
        )
    return tuple(requests)


def _process_fixture_body(
    case: FixtureCaseMetadata,
    body_path: Path,
    raw_bytes: bytes,
    output_root: Path,
) -> dict[str, object]:
    selected_path, route_value, facts = _input_path(case)
    route = DocumentRoute(route_value)
    operations = _operation_requests(case, facts, route)
    body_sha256 = sha256_bytes(raw_bytes)
    if body_sha256 != case.body_sha256 or len(raw_bytes) != case.byte_size:
        raise ProcessingReviewError(
            "materialized fixture bytes differ from case identity"
        )
    request_id = case.request_id
    engine_request = AcquisitionProcessRequest(
        target_id=case.target_id,
        family=resolve_alias(case.form) or case.form.strip().upper(),
        form_type=case.form,
        role=case.target_role,
        target_type=case.target_type,
        path_facts=facts,
        operations=tuple(
            OperationRecord(
                capability_version=operation.capability_version or "",
                output_kind=operation_output_kind(operation.operation).value,
                source_ids=(request_id,),
                operation=operation.operation,
                handler_id=operation.handler_id,
                handler_version=operation.handler_version,
            )
            for operation in operations
        ),
        inputs=(
            InputRecord(
                source_id=request_id,
                locator_provenance=case.target_url or selected_path,
                selected_path=selected_path,
                path_facts=facts,
                sha256=body_sha256,
                byte_size=len(raw_bytes),
                raw_bytes=raw_bytes,
            ),
        ),
        include_analysis_artifacts=True,
        filing_date=case.filing_date,
        report_date=case.report_date,
    )
    engine_result = AcquisitionProcessor().process(engine_request)
    result_by_operation = {item.operation: item for item in engine_result.outcomes}
    artifact_outputs: dict[str, object] = {}
    operation_results = []
    operation_records = []
    for operation in operations:
        outcome = result_by_operation[operation.operation]
        output_ref = None
        output_info = None
        sidecar_outputs = []
        if outcome.output_bytes is not None and outcome.output_sha256 is not None:
            if sha256_bytes(outcome.output_bytes) != outcome.output_sha256:
                raise ProcessingReviewError("parser output digest is invalid")
            if operation.operation == "raw":
                ext = facts.suffix.lstrip(".") if facts.suffix else "raw"
                relative_output = f"operations/raw.{ext}"
                output_path = output_root / relative_output
                atomic_write_bytes(output_path, outcome.output_bytes)
                representation = "raw"
                artifact_outputs[relative_output] = {
                    "sha256": outcome.output_sha256,
                    "byte_size": outcome.output_byte_size,
                }
            else:
                extension = "txt" if operation.operation == "render_to_txt" else "xml"
                relative_output = f"operations/{operation.operation}.{extension}"
                output_path = output_root / relative_output
                atomic_write_bytes(output_path, outcome.output_bytes)
                representation = "text_normalized" if extension == "txt" else "xml"
                artifact_outputs[relative_output] = {
                    "sha256": outcome.output_sha256,
                    "byte_size": outcome.output_byte_size,
                }

            for sidecar in outcome.sidecar_outputs:
                if (
                    sha256_bytes(sidecar.content) != sidecar.sha256
                    or len(sidecar.content) != sidecar.byte_size
                ):
                    raise ProcessingReviewError("parser sidecar digest is invalid")
                relative_sidecar = f"operations/{sidecar.name}"
                if relative_sidecar in artifact_outputs:
                    raise ProcessingReviewError("parser sidecar path is duplicated")
                sidecar_path = output_root / relative_sidecar
                atomic_write_bytes(sidecar_path, sidecar.content)
                artifact_outputs[relative_sidecar] = {
                    "sha256": sidecar.sha256,
                    "byte_size": sidecar.byte_size,
                }
                sidecar_outputs.append(
                    {
                        "path": relative_sidecar,
                        "sha256": sidecar.sha256,
                        "byte_size": sidecar.byte_size,
                    }
                )
            if operation.operation == "render_to_xml" and not any(
                item["path"] == f"operations/{UNPARSED_SECTIONS_FILE}"
                for item in sidecar_outputs
            ):
                content = serialize_unparsed_sections(())
                digest = sha256_bytes(content)
                relative_sidecar = f"operations/{UNPARSED_SECTIONS_FILE}"
                sidecar_path = output_root / relative_sidecar
                atomic_write_bytes(sidecar_path, content)
                artifact_outputs[relative_sidecar] = {
                    "sha256": digest,
                    "byte_size": len(content),
                }
                sidecar_outputs.append(
                    {
                        "path": relative_sidecar,
                        "sha256": digest,
                        "byte_size": len(content),
                    }
                )

            output_ref = StagedOutputRef(
                staging_id=output_root.name,
                path=output_path,
                representation=representation,
                output_sha256=outcome.output_sha256,
                output_size=outcome.output_byte_size or 0,
            )
            output_info = {
                "sha256": outcome.output_sha256,
                "byte_size": outcome.output_byte_size,
                "path": relative_output,
            }
        status = "available" if outcome.status == "ok" else outcome.status
        diagnostic = (
            (ProcessingDiagnostic(outcome.error, outcome.error),)
            if outcome.error is not None
            else ()
        )
        operation_fingerprint = canonical_hash(
            {
                "operation": operation.operation,
                "operation_id": operation.operation_id,
                "input_sha256": body_sha256,
                "handler_id": outcome.handler_id,
                "handler_version": outcome.handler_version,
                "status": status,
                "output_sha256": outcome.output_sha256,
                "sidecar_outputs": sidecar_outputs,
                "error": outcome.error,
            }
        )
        operation_results.append(
            OperationResult(
                operation_id=operation.operation_id,
                operation_fingerprint=operation_fingerprint,
                status=status,
                representation_id=outcome.output_kind,
                output_sha256=outcome.output_sha256,
                output_size=outcome.output_byte_size,
                handler_id=outcome.handler_id,
                handler_version=outcome.handler_version,
                diagnostics=diagnostic,
                staged_output=output_ref,
            )
        )
        operation_records.append(
            {
                "operation_id": operation.operation_id,
                "operation": operation.operation,
                "status": status,
                "output_kind": outcome.output_kind,
                "handler_id": outcome.handler_id,
                "handler_version": outcome.handler_version,
                "output": output_info,
                "sidecar_outputs": sidecar_outputs,
                "error": outcome.error,
            }
        )
    body_ref = FixtureBodyRef(
        capture_id=case.capture_id,
        target_id=case.target_id,
        path=body_path,
        sha256=body_sha256,
        byte_size=len(raw_bytes),
        selected_filename=case.selected_filename,
    )
    request = ProcessingRequest(
        target_id=case.target_id,
        accession=AccessionNumber.from_any(case.accession),
        form=case.form,
        target_role=case.target_role,
        target_type=case.target_type,
        document_path=urlsplit(case.target_url or "").path or None,
        selected_filename=case.selected_filename,
        source_origin=case.source_origin,
        body=body_ref,
        operations=operations,
    )
    assessment, assessment_fingerprint = assess_exhibit_processing(
        request,
        tuple(operation_results),
        route,
        selected_path,
    )
    profile = get_family_profile(case.form)
    allowed = allowed_operations_of(profile)
    processing = {
        "processing_id": canonical_hash(
            {
                "fixture_id": case.fixture_id,
                "capture_id": case.capture_id,
                "target_id": case.target_id,
                "body_sha256": body_sha256,
                "operations": operation_records,
            }
        ),
        "source_sha256": body_sha256,
        "source_asset_id": canonical_hash(
            {"sha256": body_sha256, "size": len(raw_bytes)}
        ),
        "route": route_value,
        "effective_path": selected_path,
        "operations": operation_records,
        "exhibit_assessment": asdict(assessment) if assessment is not None else None,
        "exhibit_assessment_fingerprint": assessment_fingerprint,
        "family_profile": {
            "family": profile.family if profile is not None else "default",
            "version": profile_version_of(profile),
            "has_toc": profile.has_toc if profile is not None else False,
            "has_sections": profile.has_sections if profile is not None else False,
            "has_notes": profile.has_notes if profile is not None else False,
            "has_xbrl": profile.has_xbrl if profile is not None else False,
            "allowed_operations": sorted(item.value for item in allowed),
        },
        "outputs": artifact_outputs,
    }
    return processing
