"""Document-acquisition processing request fixtures for tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from edgar_sec.domain.document.route import DocumentRoute

_PROCESSING_ACCESSION = "0000320193-20-000096"
_PROCESSING_ARCHIVE_ROOT = (
    "https://www.sec.gov/Archives/edgar/data/320193/"
    f"{_PROCESSING_ACCESSION.replace('-', '')}/"
)
_PROCESSING_TARGET_URL = f"{_PROCESSING_ARCHIVE_ROOT}{_PROCESSING_ACCESSION}.txt"
_PROCESSING_INDEX_URL = f"{_PROCESSING_ARCHIVE_ROOT}index.html"
_PROCESSING_SELECTED_URL = f"{_PROCESSING_ARCHIVE_ROOT}report.htm"
PROCESSING_TEST_BODY = b"fixture text body\n"
_PROCESSING_TIMESTAMP = "2026-10-11T00:00:00+00:00"


def acquired_processing_request(
    tmp_path: Path,
    *,
    lazy_selected: bool = False,
    selected_filename: str | None = None,
):
    import hashlib
    import sqlite3

    import pyarrow.parquet as pq
    import pytest

    from edgar_sec.domain.identity import AccessionNumber
    from edgar_sec.domain.sec_urls import validate_archive_url
    from edgar_sec.pipelines.document_acquisition.body_handoff import (
        get_staged_body_ref,
    )
    from edgar_sec.pipelines.document_acquisition.models import (
        AcquisitionAttempt,
        AcquisitionOutcome,
        TargetSlotResolution,
    )
    from edgar_sec.pipelines.document_acquisition.paths import (
        resolve_acquisition_paths,
    )
    from edgar_sec.pipelines.document_acquisition.plan_projection.project import (
        project_acquisition_run,
    )
    from edgar_sec.pipelines.document_acquisition.processing.models import (
        OperationRequest,
        ProcessingRequest,
    )
    from edgar_sec.pipelines.document_acquisition.run_state.mutations import (
        append_attempt_and_update_target,
        commit_attempts_and_update_target,
    )
    from tests.pipelines.document_acquisition.test_offline_acceptance import (
        _write_pinned_plan,
    )

    paths = resolve_acquisition_paths(artifacts_root=tmp_path / "artifacts")
    plan_id, target, _ = _write_pinned_plan(paths.artifacts_root)
    import edgar_sec.pipelines.document_acquisition.plan_projection.project as projection

    def compare_operation_seeds(
        database_path: Path, parts: tuple[Path, ...]
    ) -> tuple[int, int, int]:
        expected = sum(pq.ParquetFile(part).metadata.num_rows for part in parts)
        with sqlite3.connect(database_path) as connection:
            actual = connection.execute(
                "SELECT COUNT(*) FROM operation_state"
            ).fetchone()[0]
        return expected, actual, int(expected != actual)

    with pytest.MonkeyPatch.context() as fixture_patch:
        fixture_patch.setattr(
            projection, "compare_operation_seeds", compare_operation_seeds
        )
        projected = project_acquisition_run(plan_id, paths=paths)
    body_dir = paths.run_staging_root(projected.run_id)
    body_dir.mkdir(parents=True, exist_ok=True)
    relative_path = "staging/selected.txt"
    body_path = body_dir / "selected.txt"
    source_body = (
        b"<html>submitted primary response</html>"
        if lazy_selected
        else PROCESSING_TEST_BODY
    )
    selected_body = (
        b"<html>selected filing body</html>" if lazy_selected else PROCESSING_TEST_BODY
    )
    initial_relative = "staging/initial.txt"
    (body_dir / "initial.txt").write_bytes(source_body)
    body_path.write_bytes(selected_body)
    source_digest = hashlib.sha256(source_body).hexdigest()
    selected_digest = hashlib.sha256(selected_body).hexdigest()
    attempts = [
        AcquisitionAttempt(
            attempt_id="fixture-attempt-1",
            target_id=target["target_id"],
            attempt_number=1,
            attempt_kind="document_body",
            source="fixture_replay",
            requested_url=_PROCESSING_TARGET_URL,
            outcome="acquired",
            retryable=False,
            error_code=None,
            http_status=200,
            final_url=(
                _PROCESSING_SELECTED_URL
                if not lazy_selected
                else _PROCESSING_TARGET_URL
            ),
            started_at_utc=_PROCESSING_TIMESTAMP,
            finished_at_utc=_PROCESSING_TIMESTAMP,
            source_sha256=source_digest,
            source_byte_size=len(source_body),
            source_body_relative_path=initial_relative,
            selected_sha256=source_digest,
            selected_byte_size=len(source_body),
            selected_body_relative_path=(
                initial_relative if lazy_selected else relative_path
            ),
            selected_filename=selected_filename,
        )
    ]
    resolution = None
    if lazy_selected:
        index_body = b"<html>fixture index</html>"
        (body_dir / "index.html").write_bytes(index_body)
        index_digest = hashlib.sha256(index_body).hexdigest()
        attempts.extend(
            (
                AcquisitionAttempt(
                    attempt_id="fixture-index-2",
                    target_id=target["target_id"],
                    attempt_number=2,
                    attempt_kind="lazy_index",
                    source="fixture_replay",
                    requested_url=_PROCESSING_INDEX_URL,
                    outcome="acquired",
                    retryable=False,
                    error_code=None,
                    http_status=200,
                    final_url=_PROCESSING_INDEX_URL,
                    started_at_utc=_PROCESSING_TIMESTAMP,
                    finished_at_utc=_PROCESSING_TIMESTAMP,
                    source_sha256=index_digest,
                    source_byte_size=len(index_body),
                    source_body_relative_path="staging/index.html",
                    selected_sha256=None,
                    selected_byte_size=None,
                    selected_body_relative_path=None,
                ),
                AcquisitionAttempt(
                    attempt_id="fixture-selected-3",
                    target_id=target["target_id"],
                    attempt_number=3,
                    attempt_kind="document_body",
                    source="fixture_replay",
                    requested_url=_PROCESSING_SELECTED_URL,
                    outcome="acquired",
                    retryable=False,
                    error_code=None,
                    http_status=200,
                    final_url=_PROCESSING_TARGET_URL,
                    started_at_utc=_PROCESSING_TIMESTAMP,
                    finished_at_utc=_PROCESSING_TIMESTAMP,
                    source_sha256=selected_digest,
                    source_byte_size=len(selected_body),
                    source_body_relative_path=relative_path,
                    selected_sha256=selected_digest,
                    selected_byte_size=len(selected_body),
                    selected_body_relative_path=relative_path,
                ),
            )
        )
        resolution = TargetSlotResolution(
            resolution_schema_version="1",
            resolution_id="fixture-resolution",
            run_id=projected.run_id,
            target_id=target["target_id"],
            target_role="primary",
            target_type="primary",
            selector="exact_form_with_lazy_index",
            expected_statutory_type=target["form"],
            initial_sequence=1,
            index_document_type=target["form"],
            index_primary_designation=None,
            initial_observed_body_type=None,
            screen_kind="sgml_type",
            screen_result="unverifiable",
            evaluator_version=None,
            initial_body_sha256=source_digest,
            index_attempt_id="fixture-index-2",
            index_response_sha256=index_digest,
            index_parser_version="fixture-index-v1",
            matching_entry_ids=("fixture-entry-1",),
            selected_sequence=2,
            selected_retrieval_mode="direct_url",
            selected_url=_PROCESSING_SELECTED_URL,
            result="recovered",
        )
    final_attempt = attempts[-1]
    outcome = AcquisitionOutcome(
        target_id=target["target_id"],
        source="fixture_replay",
        status="acquired",
        attempt_count=len(attempts),
        last_attempt_id=final_attempt.attempt_id,
        error_code=None,
        retryable=False,
        source_sha256=selected_digest,
        source_byte_size=len(selected_body),
        source_body_relative_path=final_attempt.source_body_relative_path,
        selected_sha256=selected_digest,
        selected_byte_size=len(selected_body),
        body_lifecycle="staged",
        selected_body_relative_path=relative_path,
    )
    if lazy_selected:
        commit_attempts_and_update_target(
            paths.run_state_path(projected.run_id),
            attempts,
            outcome,
            resolution=resolution,
            recorded_at_utc=_PROCESSING_TIMESTAMP,
        )
    else:
        append_attempt_and_update_target(
            paths.run_state_path(projected.run_id), attempts[0], outcome
        )
    body = get_staged_body_ref(paths, projected.run_id, target["target_id"])
    return paths, ProcessingRequest(
        target_id=target["target_id"],
        accession=AccessionNumber.from_any(target["accession"]),
        form=target["form"],
        filing_date=target["filing_date"],
        report_date=target.get("report_date"),
        target_role=target["target_role"],
        target_type=target["target_type"],
        document_path=validate_archive_url(
            target["target_url"], target["accession"]
        ).document_path,
        selected_filename=body.selected_filename,
        source_origin=target["source_origin"],
        body=body,
        operations=(
            OperationRequest(
                operation_id="raw-identity",
                operation="raw",
                requested=True,
                support_status="supported",
                source_request_id=target["request_id"],
                capability_id="raw.selected_source",
                capability_version="v1",
                handler_id="raw_identity",
                handler_version="1",
                output_kind="raw_bytes",
            ),
            OperationRequest(
                operation_id="text-identity",
                operation="render_to_txt",
                requested=True,
                support_status="supported",
                source_request_id=target["request_id"],
                capability_id="text.plain",
                capability_version="v1",
                handler_id="normalize_document",
                handler_version="1",
                output_kind="text",
            ),
            OperationRequest(
                operation_id="xml-not-requested",
                operation="render_to_xml",
                requested=False,
                support_status="unsupported",
                source_request_id=target["request_id"],
                capability_id=None,
                capability_version=None,
                handler_id=None,
                handler_version=None,
                output_kind=None,
            ),
        ),
    )


def minimal_processing_request(
    tmp_path: Path,
    *,
    operations: tuple[Any, ...] | None = None,
    form: str = "10-K",
):
    import hashlib

    from edgar_sec.domain.identity import AccessionNumber
    from edgar_sec.pipelines.document_acquisition.paths import (
        resolve_acquisition_paths,
    )
    from edgar_sec.pipelines.document_acquisition.processing.models import (
        OperationRequest,
        ProcessingRequest,
    )
    from edgar_sec.pipelines.document_acquisition.schemas import StagedBodyRef

    paths = resolve_acquisition_paths(artifacts_root=tmp_path / "artifacts")
    run_id = "run_test"
    target_id = "target_test"
    body_path = paths.run_staging_root(run_id) / "selected.txt"
    body_path.parent.mkdir(parents=True, exist_ok=True)
    body_path.write_bytes(PROCESSING_TEST_BODY)
    digest = hashlib.sha256(PROCESSING_TEST_BODY).hexdigest()
    body = StagedBodyRef(
        run_id=run_id,
        target_id=target_id,
        path=body_path,
        sha256=digest,
        byte_size=len(PROCESSING_TEST_BODY),
        selected_filename=None,
        source_response_path=body_path,
        source_response_sha256=digest,
        source_response_byte_size=len(PROCESSING_TEST_BODY),
    )
    default_operations = (
        OperationRequest(
            operation_id="raw-test",
            operation="raw",
            requested=True,
            support_status="supported",
            source_request_id="source-test",
            capability_id="raw.selected_source",
            capability_version="v1",
            handler_id="raw_identity",
            handler_version="1",
            output_kind="raw_bytes",
        ),
        OperationRequest(
            operation_id="text-test",
            operation="render_to_txt",
            requested=True,
            support_status="supported",
            source_request_id="source-test",
            capability_id="text.plain",
            capability_version="v1",
            handler_id="normalize_document",
            handler_version="1",
            output_kind="text",
        ),
        OperationRequest(
            operation_id="xml-test",
            operation="render_to_xml",
            requested=False,
            support_status="unsupported",
            source_request_id="source-test",
            capability_id=None,
            capability_version=None,
            handler_id=None,
            handler_version=None,
            output_kind=None,
        ),
    )
    request = ProcessingRequest(
        target_id=target_id,
        accession=AccessionNumber.from_any("0000320193-23-000001"),
        form=form,
        target_role="primary",
        target_type="primary",
        document_path="filing.txt",
        selected_filename=None,
        source_origin="inventory_index",
        body=body,
        operations=default_operations if operations is None else operations,
    )
    return paths, request


def stub_processing_target_validation(
    monkeypatch: Any,
    request: Any,
    *,
    route: DocumentRoute = DocumentRoute.TEXT,
    effective_path: str = "filing.txt",
) -> None:
    import edgar_sec.pipelines.document_acquisition.processing.worker as processing

    monkeypatch.setattr(
        processing,
        "_target_row",
        lambda *_args: {
            "target_id": request.target_id,
            "target_url": _PROCESSING_TARGET_URL,
        },
    )
    monkeypatch.setattr(
        processing,
        "_effective_route",
        lambda *_args: (route, effective_path),
    )


def two_text_processing_operations(request: Any):
    from dataclasses import replace

    retry_operation = replace(
        request.operations[2],
        operation_id="text-retry",
        operation="render_to_txt",
        requested=True,
        support_status="supported",
        capability_id="text.plain",
        capability_version="v1",
        handler_id="normalize_document",
        handler_version="1",
        output_kind="text",
    )
    return replace(
        request,
        operations=(request.operations[0], request.operations[1], retry_operation),
    )


def failed_processing_operation_result(operation_id: str):
    from edgar_sec.pipelines.document_acquisition.processing.models import (
        OperationResult,
    )

    return OperationResult(
        operation_id=operation_id,
        operation_fingerprint="",
        status="failed",
        representation_id=None,
        output_sha256=None,
        output_size=None,
        handler_id=None,
        handler_version=None,
        diagnostics=(),
        staged_output=None,
    )


def processing_body_receipt(paths: Any, body: Any):
    from edgar_sec.pipelines.document_acquisition.body_handoff import (
        read_body_consumption_receipt,
    )

    return read_body_consumption_receipt(paths, body.run_id, body.target_id)


__all__ = [
    "PROCESSING_TEST_BODY",
    "acquired_processing_request",
    "failed_processing_operation_result",
    "minimal_processing_request",
    "processing_body_receipt",
    "stub_processing_target_validation",
    "two_text_processing_operations",
]
