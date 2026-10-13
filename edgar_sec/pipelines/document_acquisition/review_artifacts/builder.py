from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterable
from pathlib import Path

from edgar_sec.domain.document.route import DocumentRoute, document_route
from edgar_sec.domain.forms.common.processing import (
    AcquisitionOperation,
    DEFAULT_OPERATIONS,
)
from edgar_sec.domain.forms.families.processing_profiles import get_family_profile
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.domain.sec_urls import validate_archive_url
from edgar_sec.foundation.hashing import (
    file_sha256,
    is_sha256_hex_digest,
    sha256_text,
)
from edgar_sec.foundation.runtime.paths import validate_safe_id
from edgar_sec.foundation.serialization import canonical_hash, canonical_json
from edgar_sec.infra.storage.atomic import atomic_write_json, atomic_write_text
from edgar_sec.infra.storage.review.paths import (
    PIPELINE_REVIEW_MANIFEST_FILE,
    ReviewPaths,
)
from edgar_sec.pipelines.document_acquisition.body_handoff import (
    get_staged_body_ref,
    read_body_consumption_receipt,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.reader import (
    list_fixture_cases,
    replay_fixture_case,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.discovery import (
    FixtureCaseMetadata,
    get_fixture_case,
)
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths
from edgar_sec.pipelines.document_acquisition.processing.worker import (
    ProcessingError,
    process_target,
)
from edgar_sec.pipelines.document_acquisition.processing.models import (
    OperationRequest,
    ProcessingRequest,
    ProcessingResult,
)
from edgar_sec.pipelines.document_acquisition.project.models import (
    ProcessingResultProjection,
    ProjectedTarget,
)
from edgar_sec.pipelines.document_acquisition.review_artifacts.result_projection import (
    project_terminal_results,
)

from .models import ProcessingReviewArtifact, ReviewRunResult, ReviewSummary

OBSERVATIONS_FILE = "processing-review.json"
_ARTIFACT_VERSION = 1


class ProcessingReviewError(ValueError):
    pass


def _family_record(request: ProcessingRequest) -> dict[str, object]:
    profile = get_family_profile(request.form)
    allowed = profile.allowed_operations if profile is not None else DEFAULT_OPERATIONS
    for operation in request.operations:
        if (
            operation.requested
            and operation.support_status == "supported"
            and AcquisitionOperation(operation.operation) not in allowed
        ):
            raise ProcessingReviewError(
                "requested operation is not allowed by the form-family profile"
            )
    return {
        "family": profile.family if profile is not None else "default",
        "version": profile.version if profile is not None else "1",
        "allowed_operations": sorted(item.value for item in allowed),
    }


def _projected_target(
    projection: ProcessingResultProjection, result: ProcessingResult
) -> ProjectedTarget:
    if not is_sha256_hex_digest(projection.fingerprint):
        raise ProcessingReviewError("projection fingerprint is invalid")
    matches = (
        item for item in projection.iter_targets() if item.target_id == result.target_id
    )
    target = next(matches, None)
    if (
        target is None
        or target.processing_id != result.processing_id
        or next(matches, None) is not None
    ):
        raise ProcessingReviewError("projection does not contain the processing result")
    if (
        target.source_sha256 != result.source_sha256
        or target.route is not result.route
        or target.effective_path != result.effective_path
    ):
        raise ProcessingReviewError("projected target differs from processing result")
    return target


def _operation_records(
    request: ProcessingRequest, result: ProcessingResult, target: ProjectedTarget
) -> list[dict[str, object]]:
    request_operations = {item.operation_id: item for item in request.operations}
    projected_operations = {item.operation_id: item for item in target.operations}
    result_operations = {item.operation_id: item for item in result.operation_results}
    if (
        request_operations.keys() != result_operations.keys()
        or request_operations.keys() != projected_operations.keys()
    ):
        raise ProcessingReviewError("review operation coverage is incomplete")
    records = []
    for operation_id in sorted(request_operations):
        requested = request_operations[operation_id]
        produced = result_operations[operation_id]
        projected = projected_operations[operation_id]
        produced_representation = (
            produced.staged_output.representation
            if produced.staged_output is not None
            else None
        )
        if (
            projected.status != produced.status
            or projected.operation_fingerprint != produced.operation_fingerprint
            or projected.output_sha256 != produced.output_sha256
            or projected.output_size != produced.output_size
            or projected.handler_id != produced.handler_id
            or projected.handler_version != produced.handler_version
            or projected.staged_output_representation != produced_representation
            or projected.diagnostics != produced.diagnostics
        ):
            raise ProcessingReviewError(
                "projected operation differs from processing result"
            )
        records.append(
            {
                "operation_id": operation_id,
                "operation": requested.operation,
                "requested": requested.requested,
                "support_status": requested.support_status,
                "capability_id": requested.capability_id,
                "capability_version": requested.capability_version,
                "handler_id": produced.handler_id,
                "handler_version": produced.handler_version,
                "status": projected.status,
                "operation_fingerprint": projected.operation_fingerprint,
                "output_sha256": projected.output_sha256,
                "output_size": projected.output_size,
                "staged_output_representation": projected.staged_output_representation,
                "staged_output_path": projected.staged_output_path,
                "diagnostics": [
                    {"code": item.code, "detail": item.detail}
                    for item in projected.diagnostics
                ],
            }
        )
    return records


def _review_payload(
    fixture: FixtureCaseMetadata,
    request: ProcessingRequest,
    result: ProcessingResult,
    projection: ProcessingResultProjection,
    *,
    paths: AcquisitionPaths,
) -> dict[str, object]:
    try:
        stored_fixture = get_fixture_case(
            paths, fixture.fixture_id, fixture.capture_id, fixture.target_id
        )
    except (OSError, ValueError) as error:
        raise ProcessingReviewError("fixture metadata is unavailable") from error
    if stored_fixture != fixture:
        raise ProcessingReviewError("fixture metadata differs from fixture store")
    if (
        fixture.acquisition_status != "acquired"
        or fixture.retrieval_mode != "direct_url"
        or fixture.response_sha256 is None
        or fixture.selected_sha256 is None
        or fixture.source_byte_size is None
        or fixture.selected_byte_size is None
    ):
        raise ProcessingReviewError("fixture is not a captured direct acquisition")
    if (
        fixture.target_id != request.target_id
        or fixture.accession != str(request.accession)
        or fixture.form != request.form
        or fixture.selected_sha256 != request.body.sha256
        or fixture.selected_byte_size != request.body.byte_size
        or fixture.response_sha256 != request.body.source_response_sha256
        or fixture.source_byte_size != request.body.source_response_byte_size
    ):
        raise ProcessingReviewError("fixture identity differs from processing request")
    if (
        result.target_id != request.target_id
        or request.body.run_id != projection.run_id
    ):
        raise ProcessingReviewError("processing result run identity is inconsistent")

    with project_terminal_results(
        (request,), (result,), paths=paths, run_id=request.body.run_id
    ) as verified_projection:
        if verified_projection != projection:
            raise ProcessingReviewError(
                "projection changed before review artifact creation"
            )

    target = _projected_target(projection, result)
    family = _family_record(request)
    receipt = read_body_consumption_receipt(
        paths, request.body.run_id, request.target_id
    )
    if receipt is None:
        raise ProcessingReviewError("processing receipt is missing")
    if (
        receipt["run_id"] != request.body.run_id
        or receipt["target_id"] != request.target_id
        or receipt["selected_sha256"] != request.body.sha256
        or receipt["source_response_sha256"] != request.body.source_response_sha256
        or receipt["processing_run_id"] != result.processing_id
    ):
        raise ProcessingReviewError("processing receipt identity differs")
    receipt_sha256 = canonical_hash(receipt)
    if not is_sha256_hex_digest(receipt_sha256):
        raise ProcessingReviewError("receipt digest is invalid")

    return {
        "artifact_type": "document_acquisition.processing_review",
        "artifact_version": _ARTIFACT_VERSION,
        "fixture": {
            "fixture_id": fixture.fixture_id,
            "capture_id": fixture.capture_id,
            "capture_run_id": fixture.run_id,
            "capture_attempt_id": fixture.attempt_id,
            "target_plan_id": fixture.target_plan_id,
            "target_plan_digest": fixture.target_plan_digest,
            "target_id": fixture.target_id,
            "source_origin": fixture.source_origin,
            "target_url": fixture.target_url,
            "retrieval_mode": fixture.retrieval_mode,
            "response_sha256": fixture.response_sha256,
            "response_size": fixture.source_byte_size,
            "selected_sha256": fixture.selected_sha256,
            "selected_size": fixture.selected_byte_size,
        },
        "run_id": projection.run_id,
        "target_id": result.target_id,
        "accession": str(request.accession),
        "form": request.form,
        "family_profile": family,
        "processing": {
            "processing_id": result.processing_id,
            "source_sha256": result.source_sha256,
            "source_asset_id": result.source_asset_id,
            "route": result.route.value,
            "effective_path": result.effective_path,
            "operations": _operation_records(request, result, target),
        },
        "receipt": {
            **receipt,
            "sha256": receipt_sha256,
        },
        "projection": {
            "fingerprint": projection.fingerprint,
            "source_staged_path": target.source_staged_path,
            "source_sha256": target.source_sha256,
            "source_size": target.source_size,
        },
    }


def build_processing_review_artifact(
    fixture: FixtureCaseMetadata,
    request: ProcessingRequest,
    result: ProcessingResult,
    projection: ProcessingResultProjection,
    *,
    paths: AcquisitionPaths,
    output_path: Path,
) -> ProcessingReviewArtifact:
    payload = _review_payload(fixture, request, result, projection, paths=paths)
    artifact_sha256 = canonical_hash(payload)
    artifact = {**payload, "artifact_sha256": artifact_sha256}
    output_path = Path(output_path)
    if output_path.parent.is_symlink() or output_path.is_symlink():
        raise ProcessingReviewError("review artifact path must not be a symlink")
    encoded = canonical_json(artifact)
    if output_path.exists():
        if (
            not output_path.is_file()
            or output_path.read_text(encoding="utf-8") != encoded
        ):
            raise ProcessingReviewError(
                "review artifact conflicts with existing output"
            )
    else:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(output_path, artifact)
    return ProcessingReviewArtifact(artifact_sha256, output_path)


def _case_id(case: FixtureCaseMetadata) -> str:
    digest = sha256_text(f"{case.fixture_id}\n{case.capture_id}\n{case.target_id}")[:20]
    return validate_safe_id(f"{case.accession}--{digest}", "review_case_id")


def _operation_requests(case: FixtureCaseMetadata, route: DocumentRoute):
    profile = get_family_profile(case.form)
    allowed = profile.allowed_operations if profile is not None else DEFAULT_OPERATIONS
    version = profile.version if profile is not None else "1"
    capability_id = "form-family-profile"
    raw_support = "supported" if AcquisitionOperation.RAW in allowed else "unsupported"
    text_allowed = AcquisitionOperation.RENDER_TO_TXT in allowed
    text_requested = text_allowed and route is DocumentRoute.TEXT
    text_support = (
        "supported"
        if text_requested
        else "not_evaluated"
        if text_allowed
        else "unsupported"
    )
    return (
        OperationRequest(
            operation_id="raw",
            operation="raw",
            requested=True,
            support_status=raw_support,
            source_request_id=case.request_id,
            capability_id=capability_id,
            capability_version=version,
            handler_id=None,
            handler_version=None,
            output_kind="raw",
        ),
        OperationRequest(
            operation_id="text",
            operation="render_to_txt",
            requested=text_requested,
            support_status=text_support,
            source_request_id=case.request_id,
            capability_id=capability_id,
            capability_version=version,
            handler_id="text_passthrough" if text_requested else None,
            handler_version="1" if text_requested else None,
            output_kind="text_verbatim",
        ),
        OperationRequest(
            operation_id="xml",
            operation="render_to_xml",
            requested=True,
            support_status="unsupported",
            source_request_id=case.request_id,
            capability_id=capability_id,
            capability_version=version,
            handler_id=None,
            handler_version=None,
            output_kind="xml",
        ),
    )


def _request_for_case(
    case: FixtureCaseMetadata, *, paths: AcquisitionPaths
) -> ProcessingRequest:
    if case.target_url is None:
        raise ProcessingReviewError("fixture case has no target URL")
    document_url = case.selected_url or case.target_url
    archive_url = validate_archive_url(document_url, case.accession)
    body = get_staged_body_ref(paths, case.run_id, case.target_id)
    if (
        case.selected_sha256 != body.sha256
        or case.selected_byte_size != body.byte_size
        or case.response_sha256 != body.source_response_sha256
        or case.source_byte_size != body.source_response_byte_size
    ):
        raise ProcessingReviewError("retained S9 body differs from fixture identity")
    route = document_route(archive_url.document_path)
    return ProcessingRequest(
        target_id=case.target_id,
        accession=AccessionNumber.from_any(case.accession),
        form=case.form,
        target_role=case.target_role,
        target_type=case.target_type,
        document_path=archive_url.document_path,
        selected_filename=body.selected_filename,
        source_origin=case.source_origin,
        body=body,
        operations=_operation_requests(case, route),
    )


def _manifest_record(
    case: FixtureCaseMetadata,
    review_id: str,
    paths: ReviewPaths,
    *,
    status: str,
    output: ProcessingReviewArtifact | None,
    error: str | None = None,
) -> dict[str, object]:
    outputs = {}
    if output is not None:
        relative = output.path.relative_to(paths.root)
        outputs[OBSERVATIONS_FILE] = {
            "path": str(relative),
            "sha256": file_sha256(output.path),
        }
    return {
        "review_id": review_id,
        "fixture_id": case.fixture_id,
        "capture_id": case.capture_id,
        "target_id": case.target_id,
        "accession": case.accession,
        "response_sha256": case.response_sha256,
        "selected_sha256": case.selected_sha256,
        "status": status,
        "outputs": outputs,
        "error": None if error is None else error[:2000],
    }


def _verified_replay(case: FixtureCaseMetadata, *, paths: AcquisitionPaths) -> None:
    if case.acquisition_status != "acquired":
        raise ProcessingReviewError("fixture case is not acquired")
    with tempfile.TemporaryDirectory(prefix="acq-review-") as temporary:
        destination = Path(temporary) / "selected-body.bin"
        replay = replay_fixture_case(
            case.fixture_id,
            case.capture_id,
            case.target_id,
            destination,
            paths=paths,
        )
        if (
            replay.selected_sha256 != case.selected_sha256
            or replay.selected_byte_size != case.selected_byte_size
            or file_sha256(destination) != case.selected_sha256
        ):
            raise ProcessingReviewError("fixture replay differs from selected identity")


def build_review_artifacts(
    fixture_id: str,
    output: str | os.PathLike[str],
    *,
    paths: AcquisitionPaths,
    capture_id: str | None = None,
    target_id: str | None = None,
    accessions: Iterable[str | AccessionNumber] | None = None,
    limit: int | None = None,
    workers: int | None = None,
) -> ReviewRunResult:
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    if workers not in (None, 1):
        raise ValueError("acquisition review currently uses one worker")
    selected_accessions = (
        None
        if accessions is None
        else {str(AccessionNumber.from_any(x)) for x in accessions}
    )
    cases = [
        case
        for case in list_fixture_cases(
            paths,
            fixture_id=fixture_id,
            capture_id=capture_id,
            target_id=target_id,
        )
        if selected_accessions is None or case.accession in selected_accessions
    ]
    if limit is not None:
        selected = []
        selected_accessions_seen: set[str] = set()
        for case in cases:
            if (
                case.accession not in selected_accessions_seen
                and len(selected_accessions_seen) >= limit
            ):
                break
            selected_accessions_seen.add(case.accession)
            selected.append(case)
        cases = selected
    if not cases:
        raise ValueError("review selection is empty")

    output_root = Path(output).expanduser().resolve()
    if output_root.exists() and (
        not output_root.is_dir() or any(output_root.iterdir())
    ):
        raise ValueError(
            f"review output must be a new or empty directory: {output_root}"
        )
    output_root.mkdir(parents=True, exist_ok=True)
    review_paths = ReviewPaths(output_root, PIPELINE_REVIEW_MANIFEST_FILE)
    review_paths.case_staging_root().mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    counts = {"completed": 0, "replay_failure": 0, "execution_error": 0}

    for case in cases:
        status = "execution_error"
        artifact = None
        error = None
        try:
            _verified_replay(case, paths=paths)
        except Exception as exception:
            status = "replay_failure"
            error = str(exception) or type(exception).__name__
        else:
            case_id = _case_id(case)
            case_root = review_paths.case_dir(case_id)
            staging_root = Path(
                tempfile.mkdtemp(prefix="case-", dir=review_paths.case_staging_root())
            )
            try:
                request = _request_for_case(case, paths=paths)
                result = process_target(request, paths=paths)
                with project_terminal_results(
                    (request,), (result,), paths=paths, run_id=case.run_id
                ) as projection:
                    artifact = build_processing_review_artifact(
                        case,
                        request,
                        result,
                        projection,
                        paths=paths,
                        output_path=staging_root / OBSERVATIONS_FILE,
                    )
                case_root.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staging_root, case_root)
                artifact = ProcessingReviewArtifact(
                    artifact.artifact_sha256, case_root / OBSERVATIONS_FILE
                )
                status = "complete"
                counts["completed"] += 1
            except Exception as exception:
                shutil.rmtree(staging_root, ignore_errors=True)
                error = str(exception) or type(exception).__name__
                status = "execution_error"
        if status != "complete":
            counts[status] += 1
        records.append(
            _manifest_record(
                case,
                review_paths.review_id,
                review_paths,
                status=status,
                output=artifact if status == "complete" else None,
                error=error,
            )
        )

    manifest = "".join(canonical_json(record) + "\n" for record in records)
    atomic_write_text(review_paths.manifest_path, manifest)
    shutil.rmtree(review_paths.case_staging_root(), ignore_errors=True)
    summary = ReviewSummary(
        total=len(records),
        completed=counts["completed"],
        replay_failure=counts["replay_failure"],
        execution_error=counts["execution_error"],
    )
    return ReviewRunResult(
        review_id=review_paths.review_id,
        output_root=output_root,
        summary=summary,
        exit_code=0 if summary.replay_failure + summary.execution_error == 0 else 1,
    )


__all__ = [
    "OBSERVATIONS_FILE",
    "ProcessingReviewError",
    "build_processing_review_artifact",
    "build_review_artifacts",
]
