from __future__ import annotations

import hashlib
import json
import sqlite3
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.domain.document.route import DocumentRoute
from edgar_sec.domain.document.path_facts import DocumentPathFacts
from edgar_sec.domain.sec_urls import validate_archive_url
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.storage.review.paths import (
    PIPELINE_REVIEW_MANIFEST_FILE,
    ReviewPaths,
)
from edgar_sec.pipelines.document_acquisition.body_handoff import (
    get_staged_body_ref,
    read_body_consumption_receipt,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.capture import (
    capture_fixture_case,
    create_fixture,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.discovery import (
    get_fixture_case,
)
from edgar_sec.pipelines.document_acquisition.models import AcquisitionPolicy
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.plan_projection.project import (
    project_acquisition_run,
)
from edgar_sec.pipelines.document_acquisition.processing.worker import (
    ProcessingError,
    process_target,
)
from edgar_sec.pipelines.document_acquisition.processing.io import (
    ProcessingBudgetPolicy,
    ProcessingBudgetRegistry,
    expected_operation_pins,
)
from edgar_sec.pipelines.document_acquisition.processing.models import (
    OperationRequest,
    ProcessingRequest,
)
from edgar_sec.pipelines.document_acquisition.review_artifacts.builder import (
    build_processing_review_artifact,
    build_review_artifacts,
)
from edgar_sec.pipelines.document_acquisition.review_artifacts.result_projection import (
    project_terminal_results,
)
from edgar_sec.pipelines.document_acquisition.runner import execute_acquisition_run
from edgar_sec.pipelines.document_acquisition.run_state.store import get_target_state
from tests.pipelines.document_acquisition.test_offline_acceptance import (
    _ACCESSION,
    _ARCHIVE_ROOT,
    _FIXTURE_ID,
    _FixtureReplayTransport,
    _SyntheticTransport,
    _TARGET_URL,
    _write_pinned_plan,
)

_BODY = b"Captured direct text body\n"
_CLOCK = lambda: datetime(2026, 10, 11, tzinfo=UTC)


def _captured_text_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    target_url: str = _TARGET_URL,
    bundle_child: bool = False,
    bundle_filename: str = "primary-filing.txt",
    bundle_body: bytes = _BODY,
):
    source_root = tmp_path / "source-artifacts"
    source_paths = resolve_acquisition_paths(artifacts_root=source_root)
    plan_id, target = _write_pinned_plan(
        source_root,
        catalog_direct_selection="submitted_primary",
        target_url=target_url,
        bundle_child=bundle_child,
    )
    source_projection = project_acquisition_run(plan_id, paths=source_paths)
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.runner.derive_resources",
        lambda: type("Resources", (), {"workers": 1, "worker_ceiling": 1})(),
    )
    source_body = (
        f"<DOCUMENT><SEQUENCE>2<FILENAME>{bundle_filename}<TYPE>10-K<TEXT>".encode()
        + bundle_body
        + b"</TEXT></DOCUMENT>"
        if bundle_child
        else _BODY
    )
    source_transport = _SyntheticTransport({target_url: source_body})
    source_report = execute_acquisition_run(
        source_projection.run_id,
        retry_failures=False,
        paths=source_paths,
        policy=AcquisitionPolicy(
            max_response_bytes=4096, retain_response_evidence=True
        ),
        transport=source_transport,
        clock=_CLOCK,
    )
    assert source_report.state == "complete"
    assert source_transport.calls == [target_url]

    source_state = get_target_state(
        source_paths.run_state_path(source_projection.run_id), target["target_id"]
    )
    assert source_state is not None and source_state.last_attempt_id is not None
    create_fixture(_FIXTURE_ID, paths=source_paths)
    captured = capture_fixture_case(
        _FIXTURE_ID,
        source_projection.run_id,
        target["target_id"],
        source_state.last_attempt_id,
        paths=source_paths,
        max_response_bytes=4096,
    )
    fixture_case = get_fixture_case(
        source_paths, _FIXTURE_ID, captured.capture_id, target["target_id"]
    )

    replay_root = tmp_path / "replay-artifacts"
    replay_paths = resolve_acquisition_paths(artifacts_root=replay_root)
    replay_plan_root = replay_paths.target_plan_dir(plan_id)
    replay_plan_root.parent.mkdir(parents=True)
    shutil.copytree(source_paths.target_plan_dir(plan_id), replay_plan_root)
    replay_paths.fixtures_root.mkdir(parents=True)
    shutil.copytree(
        source_paths.fixture_root(_FIXTURE_ID), replay_paths.fixture_root(_FIXTURE_ID)
    )
    replay_projection = project_acquisition_run(plan_id, paths=replay_paths)
    replay_case = get_fixture_case(
        replay_paths, _FIXTURE_ID, captured.capture_id, target["target_id"]
    )
    replay_transport = _FixtureReplayTransport(
        replay_paths, _FIXTURE_ID, replay_case, initial_url=target_url
    )
    replay_report = execute_acquisition_run(
        replay_projection.run_id,
        retry_failures=False,
        paths=replay_paths,
        policy=AcquisitionPolicy(max_response_bytes=4096),
        transport=replay_transport,
        clock=_CLOCK,
    )
    assert replay_report.state == "complete"
    assert replay_transport.calls == [target_url]
    return (
        source_paths,
        replay_paths,
        replay_projection.run_id,
        replay_case,
        target,
    )


def _processing_request(paths, run_id, fixture_case, target):
    body = get_staged_body_ref(paths, run_id, fixture_case.target_id)
    document_path = validate_archive_url(
        str(target["target_url"]), fixture_case.accession
    ).document_path
    path_facts = (
        DocumentPathFacts.from_sgml_filename(body.selected_filename)
        if body.selected_filename is not None
        else DocumentPathFacts.from_archive_path(document_path)
    )
    request = ProcessingRequest(
        target_id=fixture_case.target_id,
        accession=AccessionNumber.from_any(fixture_case.accession),
        form=fixture_case.form,
        target_role=target["target_role"],
        target_type=target["target_type"],
        document_path=document_path,
        selected_filename=body.selected_filename,
        source_origin=target["source_origin"],
        body=body,
        operations=(
            OperationRequest(
                operation_id="raw",
                operation="raw",
                requested=True,
                support_status="supported",
                source_request_id=fixture_case.request_id,
                capability_id="raw.selected_source",
                capability_version="v1",
                handler_id="raw_identity",
                handler_version="1",
                output_kind="raw_bytes",
            ),
            OperationRequest(
                operation_id="text",
                operation="render_to_txt",
                requested=True,
                support_status="supported",
                source_request_id=fixture_case.request_id,
                capability_id=None,
                capability_version=None,
                handler_id=None,
                handler_version=None,
                output_kind=None,
            ),
            OperationRequest(
                operation_id="xml",
                operation="render_to_xml",
                requested=True,
                support_status="unsupported",
                source_request_id=fixture_case.request_id,
                capability_id=None,
                capability_version=None,
                handler_id=None,
                handler_version=None,
                output_kind="xml",
            ),
        ),
    )
    return _pin_request_operations(request, path_facts)


def _pin_request_operations(request, path_facts):
    raw, text, xml = request.operations
    raw = replace(raw, capability_id="raw.selected_source")
    raw_pins = expected_operation_pins(request, raw, path_facts)
    assert raw_pins is not None
    raw = replace(
        raw,
        capability_id=raw_pins[0],
        capability_version=raw_pins[1],
        handler_id=raw_pins[2],
        handler_version=raw_pins[3],
        output_kind=raw_pins[4],
    )
    text_pins = expected_operation_pins(request, text, path_facts)
    if text_pins is None:
        text = replace(
            text,
            requested=True,
            support_status="unsupported",
            capability_id=None,
            capability_version=None,
            handler_id=None,
            handler_version=None,
            output_kind=None,
        )
    else:
        text = replace(
            text,
            capability_id=text_pins[0],
            capability_version=text_pins[1],
            handler_id=text_pins[2],
            handler_version=text_pins[3],
            output_kind=text_pins[4],
        )
    xml = replace(
        xml,
        requested=True,
        support_status="unsupported",
        capability_id=None,
        capability_version=None,
        handler_id=None,
        handler_version=None,
        output_kind=None,
    )
    return replace(request, operations=(raw, text, xml))


def _test_budget_registry() -> ProcessingBudgetRegistry:
    from edgar_sec.engine.document_processing.capabilities import get_capability

    descriptor = get_capability("normalize_document")
    assert descriptor is not None
    return ProcessingBudgetRegistry(
        (
            ProcessingBudgetPolicy(
                budget_version="review-test-v1",
                route=DocumentRoute.TEXT,
                handler_id="normalize_document",
                handler_version=descriptor.handler_version,
                max_input_bytes=256,
                max_output_bytes=512,
                working_set_reservation_bytes=512,
            ),
        )
    )


def _process_with_test_budget(request, **kwargs):
    return process_target(request, budget_registry=_test_budget_registry(), **kwargs)


def test_captured_text_fixture_processes_and_builds_reproducible_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, paths, run_id, fixture_case, target = _captured_text_fixture(
        tmp_path, monkeypatch
    )
    request = _processing_request(paths, run_id, fixture_case, target)

    result = _process_with_test_budget(request, paths=paths)
    receipt = read_body_consumption_receipt(paths, run_id, request.target_id)
    assert result.route.value == "text"
    assert receipt is not None
    assert receipt["processing_run_id"] == result.processing_id
    artifact_path = tmp_path / "case-artifacts" / "processing-review.json"
    with project_terminal_results(
        (request,), (result,), paths=paths, run_id=run_id
    ) as projection:
        with project_terminal_results(
            (request,), (result,), paths=paths, run_id=run_id
        ) as repeated_projection:
            assert projection.fingerprint == repeated_projection.fingerprint
        projected = next(projection.iter_targets())
        assert {item.operation_id for item in projected.operations} == {
            "raw",
            "text",
            "xml",
        }
        assert {item.status for item in projected.operations} == {
            "available",
            "unsupported",
        }
        assert projected.operations[0].staged_output_path
        assert (
            projected.operations[0].output_sha256 == hashlib.sha256(_BODY).hexdigest()
        )
        for operation in projected.operations:
            if operation.staged_output_path is not None:
                staged_path = paths.run_dir(run_id) / operation.staged_output_path
                assert staged_path.is_relative_to(paths.run_staging_root(run_id))
                assert file_sha256(staged_path) == operation.output_sha256

        artifact = build_processing_review_artifact(
            fixture_case,
            request,
            result,
            projection,
            paths=paths,
            output_path=artifact_path,
        )
        saved = json.loads(artifact.path.read_text(encoding="utf-8"))
        assert saved["artifact_sha256"] == canonical_hash(
            {key: value for key, value in saved.items() if key != "artifact_sha256"}
        )
        assert saved["fixture"]["fixture_id"] == _FIXTURE_ID
        assert saved["fixture"]["selected_sha256"] == fixture_case.selected_sha256
        assert saved["family_profile"] == {
            "family": "10-K",
            "version": "v1",
            "allowed_operations": ["raw", "render_to_txt"],
        }
        assert saved["projection"]["fingerprint"] == projection.fingerprint
        assert saved["receipt"]["selected_sha256"] == request.body.sha256
        receipt_path = paths.body_consumption_receipt_path(
            run_id, request.target_id, request.body.sha256
        )
        assert saved["receipt"]["sha256"] == file_sha256(receipt_path)
        assert [item["status"] for item in saved["processing"]["operations"]] == [
            "available",
            "available",
            "unsupported",
        ]
        text_operation = saved["processing"]["operations"][1]
        assert text_operation["handler_id"] == "normalize_document"
        assert text_operation["handler_version"] == "1"
        text_path = paths.run_dir(run_id) / text_operation["staged_output_path"]
        assert text_operation["output_sha256"] == file_sha256(text_path)

        before = artifact.path.read_bytes()
        repeated = build_processing_review_artifact(
            fixture_case,
            request,
            result,
            projection,
            paths=paths,
            output_path=artifact_path,
        )
        assert repeated == artifact
        assert repeated.path.read_bytes() == before


def test_numbered_direct_child_fixture_replays_through_processing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target_url = f"{_ARCHIVE_ROOT}{_ACCESSION}-0001.txt"
    _, paths, run_id, fixture_case, target = _captured_text_fixture(
        tmp_path, monkeypatch, target_url=target_url
    )
    request = _processing_request(paths, run_id, fixture_case, target)

    result = _process_with_test_budget(request, paths=paths)
    with project_terminal_results(
        (request,), (result,), paths=paths, run_id=run_id
    ) as projection:
        projected = next(projection.iter_targets())
        assert result.route.value == "text"
        assert request.document_path == f"{_ACCESSION}-0001.txt"
        assert projected.selected_filename is None
        assert projected.source_sha256 == fixture_case.selected_sha256


def test_bundle_selected_filename_crosses_processing_and_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, paths, run_id, fixture_case, target = _captured_text_fixture(
        tmp_path, monkeypatch, bundle_child=True
    )
    request = _processing_request(paths, run_id, fixture_case, target)

    assert fixture_case.selected_filename == "primary-filing.txt"
    assert request.body.selected_filename == fixture_case.selected_filename
    assert request.selected_filename == fixture_case.selected_filename
    result = _process_with_test_budget(request, paths=paths)
    assert result.route.value == "text"
    assert result.effective_path == fixture_case.selected_filename
    assert read_body_consumption_receipt(paths, run_id, request.target_id) is not None

    with project_terminal_results(
        (request,), (result,), paths=paths, run_id=run_id
    ) as projection:
        projected = next(projection.iter_targets())
        assert projection.fingerprint
        assert projected.selected_filename == "primary-filing.txt"
        assert projected.source_sha256 == fixture_case.selected_sha256

    retained_body = request.body.path.read_bytes()
    resume_transport = _SyntheticTransport({})
    resume_report = execute_acquisition_run(
        run_id,
        retry_failures=True,
        paths=paths,
        policy=AcquisitionPolicy(max_response_bytes=4096),
        transport=resume_transport,
        clock=_CLOCK,
    )
    assert resume_report.state == "complete"
    assert resume_report.attempted_count == 0
    assert resume_transport.calls == []
    assert request.body.path.read_bytes() == retained_body


@pytest.mark.parametrize(
    ("filename", "route"),
    [("primary.pdf", "binary"), ("primary.data", "unknown")],
)
def test_bundle_filename_routes_binary_and_unrecognized_bodies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    route: str,
) -> None:
    _, paths, run_id, fixture_case, target = _captured_text_fixture(
        tmp_path,
        monkeypatch,
        bundle_child=True,
        bundle_filename=filename,
        bundle_body=b"%PDF-1.7\nsynthetic binary body"
        if filename.endswith(".pdf")
        else _BODY,
    )
    request = _processing_request(paths, run_id, fixture_case, target)
    result = _process_with_test_budget(request, paths=paths)

    assert request.selected_filename == filename
    assert result.route.value == route
    assert result.operation_results[0].status == "available"
    assert result.operation_results[1].status == "unsupported"

    with project_terminal_results(
        (request,), (result,), paths=paths, run_id=run_id
    ) as projection:
        projected = next(projection.iter_targets())
        assert projected.selected_filename == filename
        assert projected.route.value == route


def test_review_builder_uses_shared_manifest_and_case_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_paths, _, _, fixture_case, _ = _captured_text_fixture(tmp_path, monkeypatch)
    output = tmp_path / "review-run"

    result = build_review_artifacts(
        _FIXTURE_ID,
        output,
        paths=source_paths,
        capture_id=fixture_case.capture_id,
        target_id=fixture_case.target_id,
        workers=1,
    )

    assert result.summary.total == result.summary.completed == 1
    review_paths = ReviewPaths(output, PIPELINE_REVIEW_MANIFEST_FILE)
    record = json.loads(review_paths.manifest_path.read_text(encoding="utf-8"))
    assert record["fixture_id"] == _FIXTURE_ID
    assert record["capture_id"] == fixture_case.capture_id
    assert record["status"] == "complete"
    artifact_record = record["outputs"]["processing-review.json"]
    artifact_path = output / artifact_record["path"]
    assert file_sha256(artifact_path) == artifact_record["sha256"]
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["fixture"]["selected_sha256"] == fixture_case.selected_sha256
    assert artifact["family_profile"]["version"] == "v1"
    operations = {
        item["operation"]: item for item in artifact["processing"]["operations"]
    }
    assert operations["raw"]["capability_id"] == "raw.selected_source"
    assert operations["raw"]["handler_id"] == "raw_identity"
    assert operations["render_to_txt"]["capability_id"] in {None, "text.markup"}
    assert operations["render_to_xml"]["support_status"] == "not_evaluated"


def test_review_builder_rejects_tampered_fixture_request_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, _, _, fixture_case, _ = _captured_text_fixture(tmp_path, monkeypatch)
    with sqlite3.connect(paths.fixture_database_path(_FIXTURE_ID)) as connection:
        connection.execute("DROP TRIGGER immutable_case_update")
        connection.execute(
            "UPDATE cases SET request_id = ? WHERE capture_id = ? AND target_id = ?",
            ("tampered-request", fixture_case.capture_id, fixture_case.target_id),
        )
        connection.execute(
            "CREATE TRIGGER immutable_case_update BEFORE UPDATE ON cases "
            "BEGIN SELECT RAISE(ABORT, 'fixture cases are immutable'); END"
        )

    output = tmp_path / "tampered-review"
    result = build_review_artifacts(
        _FIXTURE_ID,
        output,
        paths=paths,
        capture_id=fixture_case.capture_id,
        target_id=fixture_case.target_id,
        workers=1,
    )

    assert result.summary.total == 1
    assert result.summary.execution_error == 1
    record = json.loads(
        ReviewPaths(output, PIPELINE_REVIEW_MANIFEST_FILE).manifest_path.read_text(
            encoding="utf-8"
        )
    )
    assert record["status"] == "execution_error"
    assert record["outputs"] == {}
    assert "fixture target differs from acquisition work order" in record["error"]


def test_process_target_rejects_family_disallowed_operation(
    tmp_path: Path,
) -> None:
    from tests.pipelines.document_acquisition.processing.test_worker import (
        _acquired_request,
    )

    paths, request = _acquired_request(tmp_path)
    xml = OperationRequest(
        operation_id="xml",
        operation="render_to_xml",
        requested=True,
        support_status="supported",
        source_request_id="request-xml",
        capability_id="family-profile",
        capability_version="v1",
        handler_id="xml-handler",
        handler_version="1",
        output_kind="xml",
    )
    request = replace(request, operations=(xml,))

    with pytest.raises(ProcessingError, match="not allowed by the form-family profile"):
        process_target(request, paths=paths)
