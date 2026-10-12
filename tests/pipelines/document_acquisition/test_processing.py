from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.domain.sec_urls import validate_archive_url
from edgar_sec.pipelines.document_acquisition.body_handoff import (
    get_staged_body_ref,
    read_body_consumption_receipt,
)
from edgar_sec.pipelines.document_acquisition.models import (
    AcquisitionAttempt,
    AcquisitionOutcome,
    TargetSlotResolution,
)
from edgar_sec.pipelines.document_acquisition.paths import (
    AcquisitionPaths,
    resolve_acquisition_paths,
)
from edgar_sec.pipelines.document_acquisition.plan_projection.project import (
    project_acquisition_run,
)
from edgar_sec.pipelines.document_acquisition.processing import (
    ProcessingError,
    process_target,
)
from edgar_sec.pipelines.document_acquisition.processing_models import (
    OperationRequest,
    ProcessingRequest,
)
from edgar_sec.pipelines.document_acquisition.run_state.store import (
    append_attempt_and_update_target,
    commit_attempts_and_update_target,
)
from tests.pipelines.document_acquisition.test_offline_acceptance import (
    _INDEX_URL,
    _SELECTED_URL,
    _TARGET_URL,
    _write_pinned_plan,
)

_BODY = b"fixture text body\n"
_TIMESTAMP = datetime(2026, 10, 11, tzinfo=UTC).isoformat()


def _acquired_request(
    tmp_path: Path, *, lazy_selected: bool = False
) -> tuple[AcquisitionPaths, ProcessingRequest]:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path / "artifacts")
    plan_id, target = _write_pinned_plan(paths.artifacts_root)
    projected = project_acquisition_run(plan_id, paths=paths)
    body_dir = paths.run_staging_root(projected.run_id)
    body_dir.mkdir(parents=True, exist_ok=True)
    relative_path = "staging/selected.txt"
    body_path = body_dir / "selected.txt"
    source_body = b"<html>submitted primary response</html>" if lazy_selected else _BODY
    selected_body = b"<html>selected filing body</html>" if lazy_selected else _BODY
    initial_relative = "staging/initial.txt"
    initial_path = body_dir / "initial.txt"
    initial_path.write_bytes(source_body)
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
            requested_url=_TARGET_URL,
            outcome="acquired",
            retryable=False,
            error_code=None,
            http_status=200,
            final_url=_SELECTED_URL if not lazy_selected else _TARGET_URL,
            started_at_utc=_TIMESTAMP,
            finished_at_utc=_TIMESTAMP,
            source_sha256=source_digest,
            source_byte_size=len(source_body),
            source_body_relative_path=initial_relative,
            selected_sha256=source_digest,
            selected_byte_size=len(source_body),
            selected_body_relative_path=(
                initial_relative if lazy_selected else relative_path
            ),
        )
    ]
    resolution = None
    if lazy_selected:
        index_body = b"<html>fixture index</html>"
        index_path = body_dir / "index.html"
        index_path.write_bytes(index_body)
        index_digest = hashlib.sha256(index_body).hexdigest()
        attempts.extend(
            (
                AcquisitionAttempt(
                    attempt_id="fixture-index-2",
                    target_id=target["target_id"],
                    attempt_number=2,
                    attempt_kind="lazy_index",
                    source="fixture_replay",
                    requested_url=_INDEX_URL,
                    outcome="acquired",
                    retryable=False,
                    error_code=None,
                    http_status=200,
                    final_url=_INDEX_URL,
                    started_at_utc=_TIMESTAMP,
                    finished_at_utc=_TIMESTAMP,
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
                    requested_url=_SELECTED_URL,
                    outcome="acquired",
                    retryable=False,
                    error_code=None,
                    http_status=200,
                    final_url=_TARGET_URL,
                    started_at_utc=_TIMESTAMP,
                    finished_at_utc=_TIMESTAMP,
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
            selected_url=_SELECTED_URL,
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
            recorded_at_utc=_TIMESTAMP,
        )
    else:
        append_attempt_and_update_target(
            paths.run_state_path(projected.run_id), attempts[0], outcome
        )
    body = get_staged_body_ref(paths, projected.run_id, target["target_id"])
    request = ProcessingRequest(
        target_id=target["target_id"],
        accession=AccessionNumber.from_any(target["accession"]),
        form=target["form"],
        target_role=target["target_role"],
        target_type=target["target_type"],
        document_path=validate_archive_url(
            target["target_url"], target["accession"]
        ).document_path,
        selected_filename=None,
        source_origin=target["source_origin"],
        body=body,
        operations=(
            OperationRequest(
                operation_id="raw-identity",
                operation="raw",
                requested=True,
                support_status="supported",
                source_request_id=target["request_id"],
                capability_id="raw",
                capability_version="1",
                handler_id=None,
                handler_version=None,
                output_kind="raw",
            ),
            OperationRequest(
                operation_id="text-identity",
                operation="render_to_txt",
                requested=True,
                support_status="supported",
                source_request_id=target["request_id"],
                capability_id="text-passthrough",
                capability_version="1",
                handler_id="text_passthrough",
                handler_version="1",
                output_kind="text_verbatim",
            ),
            OperationRequest(
                operation_id="xml-not-requested",
                operation="render_to_xml",
                requested=False,
                support_status="supported",
                source_request_id=target["request_id"],
                capability_id="family-xml",
                capability_version="1",
                handler_id="family-xml",
                handler_version="1",
                output_kind="xml",
            ),
        ),
    )
    return paths, request


def test_process_target_returns_deterministic_identity_results_and_receipt(
    tmp_path: Path,
) -> None:
    paths, request = _acquired_request(tmp_path)

    first = process_target(request, paths=paths)
    second = process_target(request, paths=paths)

    assert first == second
    assert first.route.value == "text"
    assert first.source_sha256 == request.body.sha256
    assert [item.status for item in first.operation_results] == [
        "available",
        "available",
        "not_requested",
    ]
    assert [item.staged_output.path for item in first.operation_results[:2]] == [
        request.body.path,
        request.body.path,
    ]
    assert first.operation_results[2].staged_output is None
    receipt = read_body_consumption_receipt(
        paths, request.body.run_id, request.target_id
    )
    assert receipt is not None
    assert receipt["processing_run_id"] == first.processing_id


def test_process_target_records_receipt_when_export_handler_is_missing(
    tmp_path: Path,
) -> None:
    paths, request = _acquired_request(tmp_path)
    operation = replace(
        request.operations[1],
        handler_id="missing-text-handler",
        handler_version="1",
    )
    request = replace(request, operations=(operation,))

    result = process_target(request, paths=paths)

    assert result.operation_results[0].status == "failed"
    assert result.operation_results[0].diagnostics[0].code == "handler_unavailable"
    assert result.operation_results[0].staged_output is None
    assert read_body_consumption_receipt(paths, request.body.run_id, request.target_id)


def test_process_target_uses_lazy_direct_selection_evidence_for_route(
    tmp_path: Path,
) -> None:
    paths, request = _acquired_request(tmp_path, lazy_selected=True)

    result = process_target(request, paths=paths)

    assert result.route.value == "markup"
    assert result.effective_path == "report.htm"
    assert result.operation_results[0].status == "available"
    assert result.operation_results[1].status == "failed"
    assert result.operation_results[1].diagnostics[0].code == "handler_unavailable"


def test_process_target_refuses_mismatched_work_order_identity_without_receipt(
    tmp_path: Path,
) -> None:
    paths, request = _acquired_request(tmp_path)

    with pytest.raises(ProcessingError, match="differs from work order"):
        process_target(replace(request, form="8-K"), paths=paths)

    assert (
        read_body_consumption_receipt(paths, request.body.run_id, request.target_id)
        is None
    )


def test_process_target_refuses_changed_staged_body_without_receipt(
    tmp_path: Path,
) -> None:
    paths, request = _acquired_request(tmp_path)
    request.body.path.write_bytes(b"changed")

    with pytest.raises(ProcessingError):
        process_target(request, paths=paths)

    assert (
        read_body_consumption_receipt(paths, request.body.run_id, request.target_id)
        is None
    )


def test_process_target_refuses_bundle_without_committed_child_filename(
    tmp_path: Path,
) -> None:
    paths, request = _acquired_request(tmp_path)
    from edgar_sec.pipelines.document_acquisition.processing import _effective_route

    with pytest.raises(ProcessingError, match="bundle child filename"):
        _effective_route(
            paths,
            request,
            {"retrieval_mode": "bundle_sequence", "_document_path": "filing.txt"},
        )

    assert (
        read_body_consumption_receipt(paths, request.body.run_id, request.target_id)
        is None
    )
