from __future__ import annotations

import multiprocessing
import os
import shutil
import tempfile
from collections import deque
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlsplit

from tqdm.auto import tqdm

from edgar_sec.foundation.runtime.resources import derive_resources

from edgar_sec.domain.document.path_facts import DocumentPathFacts
from edgar_sec.domain.document.route import DocumentRoute, content_route, document_route
from edgar_sec.domain.forms.common.aliases import resolve_alias
from edgar_sec.domain.forms.common.processing import DEFAULT_OPERATIONS
from edgar_sec.domain.forms.families.processing_profiles import get_family_profile
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.document_processing.acquisition_capabilities import (
    resolve_acquisition_capability,
)
from edgar_sec.engine.document_processing.capabilities import operation_output_kind
from edgar_sec.engine.forms.common.unparsed import (
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
from edgar_sec.foundation.runtime.memory import reclaim
from edgar_sec.foundation.serialization import canonical_hash, canonical_json
from edgar_sec.infra.storage.atomic import (
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
)
from edgar_sec.infra.storage.review.paths import (
    PIPELINE_REVIEW_MANIFEST_FILE,
    ReviewPaths,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.discovery import (
    FixtureCaseMetadata,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.reader import (
    _materialize_fixture_case,
    list_fixture_cases,
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
from edgar_sec.pipelines.document_acquisition.schemas import FixtureBodyRef

from .models import ProcessingReviewArtifact, ReviewRunResult, ReviewSummary

OBSERVATIONS_FILE = "processing-review.json"
_ARTIFACT_VERSION = 4
_OPERATIONS = ("raw", "render_to_txt", "render_to_xml")


class ProcessingReviewError(ValueError):
    pass


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
    allowed = profile.allowed_operations if profile is not None else DEFAULT_OPERATIONS
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
            "version": profile.version if profile is not None else "1",
            "has_toc": profile.has_toc if profile is not None else False,
            "has_sections": profile.has_sections if profile is not None else False,
            "has_notes": profile.has_notes if profile is not None else False,
            "has_xbrl": profile.has_xbrl if profile is not None else False,
            "allowed_operations": sorted(item.value for item in allowed),
        },
        "outputs": artifact_outputs,
    }
    return processing


def _review_payload(
    case: FixtureCaseMetadata, processing: dict[str, object]
) -> dict[str, object]:
    return {
        "artifact_type": "document_acquisition.processing_review",
        "artifact_version": _ARTIFACT_VERSION,
        "fixture": {
            "fixture_id": case.fixture_id,
            "capture_id": case.capture_id,
            "selection_source": case.selection_source,
            "inventory_entry_id": case.inventory_entry_id,
            "index_sha256": case.index_sha256,
            "target_plan_id": case.target_plan_id,
            "target_plan_digest": case.target_plan_digest,
            "target_plan_schema_version": int(case.target_plan_schema_version),
            "target_id": case.target_id,
            "source_origin": case.source_origin,
            "target_url": case.target_url,
            "retrieval_mode": case.retrieval_mode,
            "body_sha256": case.body_sha256,
            "byte_size": case.byte_size,
        },
        "capture_id": case.capture_id,
        "target_id": case.target_id,
        "accession": case.accession,
        "form": case.form,
        "target_role": case.target_role,
        "target_type": case.target_type,
        "processing": processing,
    }


def build_processing_review_artifact(
    case: FixtureCaseMetadata,
    processing: dict[str, object],
    output_path: Path,
) -> ProcessingReviewArtifact:
    payload = _review_payload(case, processing)
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
        "target_plan_id": case.target_plan_id,
        "target_plan_digest": case.target_plan_digest,
        "target_plan_schema_version": int(case.target_plan_schema_version),
        "body_sha256": case.body_sha256,
        "status": status,
        "outputs": outputs,
        "error": None if error is None else error[:2000],
    }


_RECLAIM_INTERVAL = 25


def _process_review_case_worker(
    case: FixtureCaseMetadata,
    paths: AcquisitionPaths,
    case_root: Path,
    staging_root: Path,
    review_paths: ReviewPaths,
) -> tuple[str, ProcessingReviewArtifact | None, str | None]:
    status = "execution_error"
    artifact = None
    error = None
    raw_bytes = b""
    with tempfile.TemporaryDirectory(prefix="fixture-body-") as temporary:
        body_path = Path(temporary) / "selected-body.bin"
        try:
            raw_bytes = _validated_fixture_body(case, paths, body_path)
        except Exception as exception:
            status = "fixture_verification_failure"
            error = str(exception) or type(exception).__name__
        else:
            try:
                processing = _process_fixture_body(
                    case, body_path, raw_bytes, staging_root
                )
                artifact = build_processing_review_artifact(
                    case, processing, staging_root / OBSERVATIONS_FILE
                )
                case_root.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staging_root, case_root)
                artifact = ProcessingReviewArtifact(
                    artifact.artifact_sha256, case_root / OBSERVATIONS_FILE
                )
                status = "complete"
            except Exception as exception:
                error = str(exception) or type(exception).__name__
    if status != "complete":
        shutil.rmtree(staging_root, ignore_errors=True)
    del raw_bytes
    return status, artifact, error


def build_review_artifacts(
    fixture_id: str,
    output: str | os.PathLike[str],
    *,
    paths: AcquisitionPaths,
    limit: int | None = None,
    workers: int | None = None,
    no_progress: bool = False,
) -> ReviewRunResult:
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    cases = list(list_fixture_cases(paths, fixture_id=fixture_id))
    if limit is not None:
        cases = cases[:limit]
    if not cases:
        raise ValueError("fixture has no parser-body cases")

    resources = derive_resources()
    if workers is not None and workers < 1:
        raise ValueError("workers must be positive")
    worker_count = (
        min(resources.workers, resources.worker_ceiling)
        if workers is None
        else min(workers, resources.worker_ceiling)
    )
    worker_count = max(1, min(worker_count, len(cases)))

    requested_output = Path(output).expanduser()
    if requested_output.is_symlink():
        raise ValueError("review output must not be a symlink")
    output_root = requested_output.resolve()
    if output_root.exists() and (
        not output_root.is_dir() or any(output_root.iterdir())
    ):
        raise ValueError(
            f"review output must be a new or empty directory: {output_root}"
        )
    output_root.mkdir(parents=True, exist_ok=True)
    review_paths = ReviewPaths(output_root, PIPELINE_REVIEW_MANIFEST_FILE)
    review_paths.case_staging_root().mkdir(parents=True, exist_ok=True)
    records = []
    counts = {"complete": 0, "fixture_verification_failure": 0, "execution_error": 0}

    if worker_count == 1:
        with tqdm(
            cases,
            desc="Parser review",
            unit="case",
            dynamic_ncols=True,
            disable=no_progress,
        ) as pbar:
            for case in pbar:
                case_root = review_paths.case_dir(_case_id(case))
                staging_root = Path(
                    tempfile.mkdtemp(
                        prefix="case-", dir=review_paths.case_staging_root()
                    )
                )
                st, art, err = _process_review_case_worker(
                    case, paths, case_root, staging_root, review_paths
                )
                counts[st] += 1
                records.append(
                    _manifest_record(
                        case,
                        review_paths.review_id,
                        review_paths,
                        status=st,
                        output=art,
                        error=err,
                    )
                )
                if (
                    counts["complete"]
                    + counts["fixture_verification_failure"]
                    + counts["execution_error"]
                ) % _RECLAIM_INTERVAL == 0:
                    reclaim()
    else:
        executor = ProcessPoolExecutor(
            max_workers=worker_count,
            mp_context=multiprocessing.get_context("spawn"),
        )
        pending: deque[
            tuple[
                FixtureCaseMetadata,
                Future[tuple[str, ProcessingReviewArtifact | None, str | None]],
            ]
        ] = deque()

        def _drain_oldest(pbar) -> None:
            c, fut = pending.popleft()
            try:
                st, art, err = fut.result()
            except Exception as exc:
                st, art, err = "execution_error", None, str(exc)
            counts[st] += 1
            records.append(
                _manifest_record(
                    c,
                    review_paths.review_id,
                    review_paths,
                    status=st,
                    output=art,
                    error=err,
                )
            )
            pbar.update(1)
            processed = (
                counts["complete"]
                + counts["fixture_verification_failure"]
                + counts["execution_error"]
            )
            if processed % _RECLAIM_INTERVAL == 0:
                reclaim()

        try:
            with tqdm(
                total=len(cases),
                desc="Parser review",
                unit="case",
                dynamic_ncols=True,
                disable=no_progress,
            ) as pbar:
                for case in cases:
                    case_root = review_paths.case_dir(_case_id(case))
                    staging_root = Path(
                        tempfile.mkdtemp(
                            prefix="case-", dir=review_paths.case_staging_root()
                        )
                    )
                    fut = executor.submit(
                        _process_review_case_worker,
                        case,
                        paths,
                        case_root,
                        staging_root,
                        review_paths,
                    )
                    pending.append((case, fut))
                    if len(pending) >= worker_count * 2:
                        _drain_oldest(pbar)

                while pending:
                    _drain_oldest(pbar)
        except KeyboardInterrupt:
            executor.shutdown(wait=False, cancel_futures=True)
            raise
        finally:
            executor.shutdown(wait=True)

    manifest = "".join(canonical_json(record) + "\n" for record in records)
    atomic_write_text(review_paths.manifest_path, manifest)
    shutil.rmtree(review_paths.case_staging_root(), ignore_errors=True)
    summary = ReviewSummary(
        total=len(records),
        completed=counts["complete"],
        fixture_verification_failure=counts["fixture_verification_failure"],
        execution_error=counts["execution_error"],
    )
    return ReviewRunResult(
        review_id=review_paths.review_id,
        output_root=output_root,
        summary=summary,
        exit_code=0
        if summary.fixture_verification_failure + summary.execution_error == 0
        else 1,
    )


__all__ = [
    "OBSERVATIONS_FILE",
    "ProcessingReviewError",
    "build_processing_review_artifact",
    "build_review_artifacts",
]
