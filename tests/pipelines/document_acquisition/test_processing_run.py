from __future__ import annotations

import hashlib
import builtins
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.sec_http.client import SecHttpClient
from edgar_sec.pipelines.document_acquisition import processing_run
from edgar_sec.pipelines.document_acquisition.body_handoff import get_staged_body_ref
from edgar_sec.pipelines.document_acquisition.models import (
    AcquisitionAttempt,
    AcquisitionOutcome,
    OperationAttempt,
)
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths
from edgar_sec.pipelines.document_acquisition.processing_models import (
    OperationRequest,
    ProcessingRequest,
    StagedOutputRef,
)
from edgar_sec.pipelines.document_acquisition.run_state.locks import (
    RunLock,
    RunLockError,
)
from edgar_sec.pipelines.document_acquisition.run_state.operations import (
    append_operation_attempt,
    get_operation_state,
    operation_attempt_id,
)
from edgar_sec.pipelines.document_acquisition.run_state.store import (
    append_attempt_and_update_target,
    get_target_state,
)
from edgar_sec.pipelines.document_acquisition.run_validation import (
    iter_resolved_work_order_operations,
    iter_work_order_rows,
    load_validated_work_order,
)
from tests.acquisition_run_fixture import make_acquisition_run

_TIMESTAMP = datetime(2026, 10, 12, tzinfo=UTC).isoformat().replace("+00:00", "Z")


def _operation_id(target_id: str, operation: str) -> str:
    return canonical_hash([target_id, operation])


def _acquired_request(tmp_path: Path) -> tuple[AcquisitionPaths, ProcessingRequest]:
    paths, run_id, target = make_acquisition_run(tmp_path / "artifacts", lazy=False)
    body = b"offline coordinator fixture\n"
    relative_path = "staging/selected.txt"
    body_path = paths.run_dir(run_id) / relative_path
    body_path.parent.mkdir(parents=True, exist_ok=True)
    body_path.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    attempt = AcquisitionAttempt(
        attempt_id="fixture-body-attempt",
        target_id=target["target_id"],
        attempt_number=1,
        attempt_kind="document_body",
        source="fixture_replay",
        requested_url=target["target_url"],
        outcome="acquired",
        retryable=False,
        error_code=None,
        http_status=200,
        final_url=target["target_url"],
        started_at_utc=_TIMESTAMP,
        finished_at_utc=_TIMESTAMP,
        source_sha256=digest,
        source_byte_size=len(body),
        source_body_relative_path=relative_path,
        selected_sha256=digest,
        selected_byte_size=len(body),
        selected_body_relative_path=relative_path,
    )
    append_attempt_and_update_target(
        paths.run_state_path(run_id),
        attempt,
        AcquisitionOutcome(
            target_id=target["target_id"],
            source="fixture_replay",
            status="acquired",
            attempt_count=1,
            last_attempt_id=attempt.attempt_id,
            error_code=None,
            retryable=False,
            source_sha256=digest,
            source_byte_size=len(body),
            source_body_relative_path=relative_path,
            selected_sha256=digest,
            selected_byte_size=len(body),
            body_lifecycle="staged",
            selected_body_relative_path=relative_path,
        ),
    )
    target = next(iter_work_order_rows(load_validated_work_order(paths, run_id)))
    body_ref = get_staged_body_ref(paths, run_id, target["target_id"])
    operations = tuple(iter_resolved_work_order_operations(paths, run_id))
    return paths, ProcessingRequest(
        target_id=target["target_id"],
        accession=AccessionNumber.from_any(target["accession"]),
        form=target["form"],
        target_role=target["target_role"],
        target_type=target["target_type"],
        document_path=target["target_url"].rsplit("/", 1)[-1],
        selected_filename=body_ref.selected_filename,
        source_origin=target["source_origin"],
        body=body_ref,
        operations=processing_run._operation_requests(operations),
    )


def _record_operation(
    paths: AcquisitionPaths,
    run_id: str,
    target_id: str,
    operation: str,
    *,
    outcome: str,
    retryable: bool = False,
) -> None:
    operation_id = _operation_id(target_id, operation)
    state = get_operation_state(paths.run_state_path(run_id), operation_id)
    assert state is not None
    attempt_number = state.attempt_count + 1
    append_operation_attempt(
        paths.run_state_path(run_id),
        OperationAttempt(
            attempt_id=operation_attempt_id(operation_id, attempt_number),
            operation_id=operation_id,
            attempt_number=attempt_number,
            outcome=outcome,
            retryable=retryable,
            error_code="handler_failed:ValueError" if outcome == "failed" else None,
            started_at_utc=_TIMESTAMP,
            finished_at_utc=_TIMESTAMP,
        ),
    )


def _fake_result(request, *, failed_operation: str | None = None):
    processing_id = canonical_hash([request.target_id, request.body.sha256])
    operation_results = []
    for operation in request.operations:
        status = (
            "failed"
            if operation.operation == failed_operation
            else "unsupported"
            if operation.requested and operation.support_status == "unsupported"
            else "not_requested"
            if not operation.requested
            else "available"
        )
        staged_output = (
            StagedOutputRef(
                staging_id=processing_id,
                path=request.body.path,
                representation=(
                    "raw"
                    if operation.operation == "raw"
                    else "text_normalized"
                    if operation.operation == "render_to_txt"
                    else "xml"
                ),
                output_sha256=request.body.sha256,
                output_size=request.body.byte_size,
            )
            if status == "available"
            else None
        )
        operation_results.append(
            SimpleNamespace(
                operation_id=operation.operation_id,
                operation_fingerprint=canonical_hash(
                    [operation.operation_id, "test-fingerprint"]
                ),
                status=status,
                representation_id=None,
                output_sha256=request.body.sha256 if staged_output else None,
                output_size=request.body.byte_size if staged_output else None,
                handler_id=operation.handler_id,
                handler_version=operation.handler_version,
                diagnostics=(
                    (SimpleNamespace(code="handler_failed:ValueError", detail=""),)
                    if status == "failed"
                    else ()
                ),
                staged_output=staged_output,
            )
        )
    return SimpleNamespace(
        processing_id=processing_id,
        target_id=request.target_id,
        source_sha256=request.body.sha256,
        source_asset_id="asset_" + canonical_hash([request.target_id])[:32],
        operation_results=tuple(operation_results),
    )


def test_processes_acquired_work_order_and_returns_safe_complete_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, request = _acquired_request(tmp_path)
    run_id = request.body.run_id
    attempted_requests = []

    def local_process(target_request, *, paths):
        attempted_requests.append(target_request)
        return _fake_result(target_request)

    monkeypatch.setattr(processing_run, "process_target", local_process)
    summary = processing_run.execute_processing_run(run_id, paths, workers=4)

    assert summary == {
        "success": True,
        "complete": True,
        "run_id": run_id,
        "target_counts": {"acquired": 1},
        "operation_counts": {"available": 1, "not_requested": 2},
        "attempted_target_count": 1,
    }
    assert len(attempted_requests) == 1
    assert [item.operation for item in attempted_requests[0].operations] == [
        "raw",
        "render_to_txt",
        "render_to_xml",
    ]
    assert "body" not in json.dumps(summary).casefold()
    assert str(paths.artifacts_root) not in json.dumps(summary)
    result_path = (
        paths.run_staging_root(run_id) / "processing" / f"{request.target_id}.json"
    )
    stored = json.loads(result_path.read_text(encoding="utf-8"))
    assert all(
        not Path(operation["staged_output"]["path"]).is_absolute()
        for operation in stored["operations"]
        if operation["staged_output"] is not None
    )

    resumed = processing_run.execute_processing_run(run_id, paths)
    assert resumed["attempted_target_count"] == 0
    assert len(attempted_requests) == 1


def test_blocks_unacquired_targets_without_receipt_or_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, run_id, target = make_acquisition_run(
        tmp_path / "artifacts", executable=False
    )
    calls = []
    monkeypatch.setattr(
        processing_run,
        "process_target",
        lambda *args, **kwargs: calls.append(args),
    )

    summary = processing_run.execute_processing_run(run_id, paths)

    assert summary["complete"] is True
    assert summary["success"] is False
    assert summary["target_counts"] == {"skipped": 1}
    assert summary["operation_counts"] == {"blocked": 1, "not_requested": 2}
    assert calls == []
    assert (
        get_target_state(paths.run_state_path(run_id), target["target_id"]).outcome
        == "skipped"
    )
    assert list(paths.run_dir(run_id).glob("handoff/receipts/**/*.json")) == []


def test_retry_failures_only_retries_retryable_operation_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, request = _acquired_request(tmp_path)
    run_id = request.body.run_id
    target_id = request.target_id
    _record_operation(
        paths,
        run_id,
        target_id,
        "raw",
        outcome="failed",
        retryable=True,
    )
    calls = []
    monkeypatch.setattr(
        processing_run,
        "process_target",
        lambda target_request, *, paths: (
            calls.append(target_request) or _fake_result(target_request)
        ),
    )

    skipped = processing_run.execute_processing_run(run_id, paths)
    assert skipped["complete"] is True
    assert skipped["operation_counts"] == {"failed": 1, "not_requested": 2}
    assert calls == []

    retried = processing_run.execute_processing_run(run_id, paths, retry_failures=True)
    assert retried["success"] is True
    assert retried["operation_counts"] == {"available": 1, "not_requested": 2}
    assert len(calls) == 1
    assert (
        get_operation_state(
            paths.run_state_path(run_id), _operation_id(target_id, "raw")
        ).attempt_count
        == 2
    )


def test_target_resume_reuses_available_and_blocked_results_only_selecting_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, original = _acquired_request(tmp_path)
    target_id = original.target_id
    run_id = original.body.run_id
    source_id = original.operations[0].source_request_id
    successful = OperationRequest(
        operation_id=_operation_id(target_id, "render_to_txt"),
        operation="render_to_txt",
        requested=True,
        support_status="supported",
        source_request_id=source_id,
        capability_id="text.normalized",
        capability_version="v1",
        handler_id="text_normalizer",
        handler_version="v1",
        output_kind="text",
    )
    blocked = OperationRequest(
        operation_id=_operation_id(target_id, "render_to_xml"),
        operation="render_to_xml",
        requested=True,
        support_status="supported",
        source_request_id=source_id,
        capability_id="xml.rendered",
        capability_version="v1",
        handler_id="render_xml",
        handler_version="v1",
        output_kind="xml",
    )
    request = original.__class__(
        target_id=original.target_id,
        accession=original.accession,
        form=original.form,
        target_role=original.target_role,
        target_type=original.target_type,
        document_path=original.document_path,
        selected_filename=original.selected_filename,
        source_origin=original.source_origin,
        body=original.body,
        operations=tuple(
            successful
            if item.operation == "render_to_txt"
            else blocked
            if item.operation == "render_to_xml"
            else item
            for item in original.operations
        ),
    )
    relative_body = original.body.path.relative_to(
        paths.run_staging_root(run_id)
    ).as_posix()
    prior = {
        "operations": [
            {
                "operation_id": successful.operation_id,
                "operation_fingerprint": "a" * 64,
                "status": "available",
                "representation_id": "text-normalized-v1",
                "output_sha256": original.body.sha256,
                "output_size": original.body.byte_size,
                "result_handler_id": successful.handler_id,
                "result_handler_version": successful.handler_version,
                "diagnostic_codes": [],
                "staged_output": {
                    "staging_id": "processing-prior",
                    "path": relative_body,
                    "representation": "text_normalized",
                    "sha256": original.body.sha256,
                    "byte_size": original.body.byte_size,
                },
            },
            {
                "operation_id": blocked.operation_id,
                "operation_fingerprint": "b" * 64,
                "status": "blocked",
                "representation_id": None,
                "output_sha256": None,
                "output_size": None,
                "result_handler_id": None,
                "result_handler_version": None,
                "diagnostic_codes": ["budget_refused"],
                "staged_output": None,
            },
        ]
    }
    states = {
        original.operations[0].operation_id: SimpleNamespace(
            status="failed", retryable=True
        ),
        successful.operation_id: SimpleNamespace(status="succeeded", retryable=False),
        blocked.operation_id: SimpleNamespace(status="failed", retryable=False),
    }
    received = []
    expected_result = object()
    unsafe_calls = []

    def target_only_process(processing_request, *, paths):
        unsafe_calls.append(processing_request)
        return expected_result

    monkeypatch.setattr(processing_run, "process_target", target_only_process)
    with pytest.raises(processing_run.ProcessingRunIntegrationError):
        processing_run._process_target(
            request,
            paths=paths,
            prior_result=prior,
            states=states,
            retry_failures=True,
        )
    assert unsafe_calls == []

    def selective_process(
        processing_request,
        *,
        paths,
        prior_results,
        selected_operation_ids,
    ):
        received.append((prior_results, selected_operation_ids))
        return SimpleNamespace(
            operation_results=(
                *prior_results,
                SimpleNamespace(
                    operation_id=original.operations[0].operation_id,
                    status="available",
                ),
            )
        )

    monkeypatch.setattr(processing_run, "process_target", selective_process)

    result = processing_run._process_target(
        request,
        paths=paths,
        prior_result=prior,
        states=states,
        retry_failures=True,
    )

    assert len(result.operation_results) == len(request.operations)
    assert {item.operation_id for item in result.operation_results} == {
        item.operation_id for item in request.operations
    }
    assert received[0][1] == (original.operations[0].operation_id,)
    assert [item.operation_id for item in received[0][0]] == [
        successful.operation_id,
        blocked.operation_id,
    ]
    assert [item.status for item in received[0][0]] == ["available", "blocked"]


def test_raw_body_manifest_and_retry_validation_never_read_or_hash_selected_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, original = _acquired_request(tmp_path)
    run_id = original.body.run_id
    target = next(iter_work_order_rows(load_validated_work_order(paths, run_id)))
    resolved_rows = [
        dict(row) for row in iter_resolved_work_order_operations(paths, run_id)
    ]
    raw_row = next(row for row in resolved_rows if row["operation"] == "raw")
    text_row = next(row for row in resolved_rows if row["operation"] == "render_to_txt")
    xml_row = next(row for row in resolved_rows if row["operation"] == "render_to_xml")
    source_id = raw_row["source_request_id"]
    for row, capability, handler, output_kind in (
        (text_row, "text.normalized", "text_normalizer", "text"),
        (xml_row, "xml.rendered", "render_xml", "xml"),
    ):
        row.update(
            requested=True,
            selected=True,
            request_mode="profile",
            source_request_id=source_id,
            input_ordinal=0,
            input_role="selected_target_body",
            support_status="supported",
            support_reason=None,
            capability_id=capability,
            capability_version="v1",
            handler_id=handler,
            handler_version="v1",
            output_kind=output_kind,
        )
    rows = tuple(resolved_rows)
    request = replace(original, operations=processing_run._operation_requests(rows))
    processing_id = canonical_hash([run_id, request.target_id, "budget-refusal"])
    derived_path = paths.run_staging_root(run_id) / "derived" / "partial.xml"
    derived_path.parent.mkdir(parents=True, exist_ok=True)
    derived_bytes = b"derived output remains digest checked"
    derived_path.write_bytes(derived_bytes)
    derived_digest = hashlib.sha256(derived_bytes).hexdigest()

    def result_for(row, status, *, staged_output=None, code=None):
        output_sha = staged_output.output_sha256 if staged_output else None
        output_size = staged_output.output_size if staged_output else None
        return SimpleNamespace(
            operation_id=row["operation_id"],
            operation_fingerprint=canonical_hash([row["operation_id"], "attempt"]),
            status=status,
            representation_id=staged_output.representation if staged_output else None,
            output_sha256=output_sha,
            output_size=output_size,
            handler_id=row["handler_id"],
            handler_version=row["handler_version"],
            diagnostics=(SimpleNamespace(code=code, detail=""),) if code else (),
            staged_output=staged_output,
        )

    result = SimpleNamespace(
        processing_id=processing_id,
        target_id=request.target_id,
        source_sha256=request.body.sha256,
        source_asset_id="asset_offline_fixture",
        operation_results=(
            result_for(
                raw_row,
                "available",
                staged_output=StagedOutputRef(
                    staging_id=processing_id,
                    path=request.body.path,
                    representation="raw",
                    output_sha256=request.body.sha256,
                    output_size=request.body.byte_size,
                ),
            ),
            result_for(text_row, "blocked", code="budget_refused"),
            result_for(
                xml_row,
                "failed",
                staged_output=StagedOutputRef(
                    staging_id=processing_id,
                    path=derived_path,
                    representation="xml",
                    output_sha256=derived_digest,
                    output_size=len(derived_bytes),
                ),
                code="handler_failed:ValueError",
            ),
        ),
    )
    original_file_sha256 = processing_run.file_sha256
    hashed_paths = []
    opened_paths = []
    real_open = builtins.open

    def guarded_hash(path):
        resolved = Path(path).resolve()
        hashed_paths.append(resolved)
        if resolved == request.body.path.resolve():
            raise AssertionError("selected source body must not be hashed")
        return original_file_sha256(path)

    def guarded_open(path, *args, **kwargs):
        resolved = Path(path).resolve()
        opened_paths.append(resolved)
        if resolved == request.body.path.resolve():
            raise AssertionError("selected source body must not be opened")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(processing_run, "file_sha256", guarded_hash)
    monkeypatch.setattr(builtins, "open", guarded_open)
    processing_run._persist_processing_result(paths, target, request, result, rows)
    manifest = processing_run._read_prior_processing_result(
        paths, run_id, target, request.body, rows
    )
    assert manifest["body_verified_by_processing"] is False
    prior = processing_run._prior_results(
        paths,
        run_id,
        manifest,
        (raw_row["operation_id"], text_row["operation_id"]),
    )
    states = {
        raw_row["operation_id"]: SimpleNamespace(status="succeeded", retryable=False),
        text_row["operation_id"]: SimpleNamespace(status="failed", retryable=False),
        xml_row["operation_id"]: SimpleNamespace(status="failed", retryable=True),
    }
    received = []

    def selective_process(
        retry_request, *, paths, prior_results, selected_operation_ids
    ):
        received.append((prior_results, selected_operation_ids))
        return SimpleNamespace(
            operation_results=(*prior_results, result.operation_results[2])
        )

    monkeypatch.setattr(processing_run, "process_target", selective_process)
    processing_run._process_target(
        request,
        paths=paths,
        prior_result=manifest,
        states=states,
        retry_failures=True,
    )

    assert received[0][1] == (xml_row["operation_id"],)
    assert [item.status for item in received[0][0]] == ["available", "blocked"]
    assert {
        item.operation_id for item in (*received[0][0], result.operation_results[2])
    } == {row["operation_id"] for row in rows}
    assert request.body.path.resolve() not in hashed_paths
    assert request.body.path.resolve() not in opened_paths
    assert hashed_paths.count(derived_path.resolve()) == 2


def test_unsupported_default_candidate_is_preserved_as_a_resolved_request() -> None:
    target_id = "target-1"
    source_id = "selected-source"
    rows = tuple(
        {
            "operation_id": _operation_id(target_id, operation),
            "target_id": target_id,
            "operation": operation,
            "requested": operation in {"raw", "render_to_xml"},
            "request_mode": (
                "mandatory_raw"
                if operation == "raw"
                else "default_candidate"
                if operation == "render_to_xml"
                else "not_requested"
            ),
            "selected": operation == "raw",
            "source_request_id": source_id if operation == "raw" else None,
            "input_role": "selected_target_body" if operation == "raw" else None,
            "support_status": "supported"
            if operation == "raw"
            else "unsupported"
            if operation == "render_to_xml"
            else "not_evaluated",
            "support_reason": None,
            "capability_id": "raw.selected_source" if operation == "raw" else None,
            "capability_version": "v1" if operation == "raw" else None,
            "handler_id": "raw_identity" if operation == "raw" else None,
            "handler_version": "raw-v1" if operation == "raw" else None,
            "output_kind": "raw_bytes" if operation == "raw" else None,
        }
        for operation in ("raw", "render_to_txt", "render_to_xml")
    )

    projected = processing_run._operation_requests(rows)

    assert projected[2].requested is True
    assert projected[2].support_status == "unsupported"
    assert projected[2].capability_id is None
    assert projected[2].handler_id is None


def test_malformed_work_order_refuses_before_any_processing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, request = _acquired_request(tmp_path)
    manifest_path = paths.run_manifest_path(request.body.run_id)
    manifest_path.write_text("{}", encoding="utf-8")
    calls = []
    monkeypatch.setattr(
        processing_run,
        "process_target",
        lambda *args, **kwargs: calls.append(args),
    )

    with pytest.raises((KeyError, ValueError)):
        processing_run.execute_processing_run(request.body.run_id, paths)

    assert calls == []


def test_active_acquisition_lock_excludes_processing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, request = _acquired_request(tmp_path)
    calls = []
    monkeypatch.setattr(
        processing_run,
        "process_target",
        lambda *args, **kwargs: calls.append(args),
    )

    with RunLock(paths.run_lock_path(request.body.run_id), request.body.run_id):
        with pytest.raises(RunLockError, match="already locked"):
            processing_run.execute_processing_run(request.body.run_id, paths)

    assert calls == []


def test_processing_does_not_construct_sec_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, request = _acquired_request(tmp_path)
    constructions = []

    def fail_transport(*args, **kwargs):
        constructions.append((args, kwargs))
        raise AssertionError("processing must not construct SEC transport")

    monkeypatch.setattr(SecHttpClient, "__init__", fail_transport)

    summary = processing_run.execute_processing_run(request.body.run_id, paths)

    assert summary["complete"] is True
    assert constructions == []
