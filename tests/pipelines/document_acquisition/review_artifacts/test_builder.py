from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.domain.sec_urls import validate_archive_url
from edgar_sec.domain.forms.families.processing_profiles import get_family_profile
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
from edgar_sec.pipelines.document_acquisition.fixture_operator import (
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
from edgar_sec.pipelines.document_acquisition.processing import (
    ProcessingError,
    process_target,
)
from edgar_sec.pipelines.document_acquisition.processing_models import (
    OperationRequest,
    ProcessingRequest,
)
from edgar_sec.pipelines.document_acquisition.review_artifacts.builder import (
    build_processing_review_artifact,
    build_review_artifacts,
)
from edgar_sec.pipelines.document_acquisition.result_projection import (
    project_terminal_results,
)
from edgar_sec.pipelines.document_acquisition.runner import execute_acquisition_run
from edgar_sec.pipelines.document_acquisition.run_state.store import get_target_state
from tests.pipelines.document_acquisition.test_offline_acceptance import (
    _FIXTURE_ID,
    _FixtureReplayTransport,
    _SyntheticTransport,
    _TARGET_URL,
    _write_pinned_plan,
)

_BODY = b"Captured direct text body\n"
_CLOCK = lambda: datetime(2026, 10, 11, tzinfo=UTC)


def _captured_text_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source_root = tmp_path / "source-artifacts"
    source_paths = resolve_acquisition_paths(artifacts_root=source_root)
    plan_id, target = _write_pinned_plan(
        source_root, catalog_direct_selection="submitted_primary"
    )
    source_projection = project_acquisition_run(plan_id, paths=source_paths)
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.runner.derive_resources",
        lambda: type("Resources", (), {"workers": 1, "worker_ceiling": 1})(),
    )
    source_transport = _SyntheticTransport({_TARGET_URL: _BODY})
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
    assert source_transport.calls == [_TARGET_URL]

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
    replay_transport = _FixtureReplayTransport(replay_paths, _FIXTURE_ID, replay_case)
    replay_report = execute_acquisition_run(
        replay_projection.run_id,
        retry_failures=False,
        paths=replay_paths,
        policy=AcquisitionPolicy(max_response_bytes=4096),
        transport=replay_transport,
        clock=_CLOCK,
    )
    assert replay_report.state == "complete"
    assert replay_transport.calls == [_TARGET_URL]
    return (
        source_paths,
        replay_paths,
        replay_projection.run_id,
        replay_case,
        target,
    )


def _processing_request(paths, run_id, fixture_case, target):
    body = get_staged_body_ref(paths, run_id, fixture_case.target_id)
    profile = get_family_profile(fixture_case.form)
    assert profile is not None
    profile_version = profile.version
    request = ProcessingRequest(
        target_id=fixture_case.target_id,
        accession=AccessionNumber.from_any(fixture_case.accession),
        form=fixture_case.form,
        target_role="primary",
        target_type="primary",
        document_path=validate_archive_url(
            str(target["target_url"]), fixture_case.accession
        ).document_path,
        selected_filename=None,
        source_origin="catalog_direct",
        body=body,
        operations=(
            OperationRequest(
                operation_id="raw",
                operation="raw",
                requested=True,
                support_status="supported",
                source_request_id=fixture_case.request_id,
                capability_id="family-profile",
                capability_version=profile_version,
                handler_id=None,
                handler_version=None,
                output_kind="raw",
            ),
            OperationRequest(
                operation_id="text",
                operation="render_to_txt",
                requested=True,
                support_status="supported",
                source_request_id=fixture_case.request_id,
                capability_id="family-profile",
                capability_version=profile_version,
                handler_id="text_passthrough",
                handler_version="1",
                output_kind="text_verbatim",
            ),
            OperationRequest(
                operation_id="xml",
                operation="render_to_xml",
                requested=True,
                support_status="unsupported",
                source_request_id=fixture_case.request_id,
                capability_id="family-profile",
                capability_version=profile_version,
                handler_id=None,
                handler_version=None,
                output_kind="xml",
            ),
        ),
    )
    return request


def test_captured_text_fixture_processes_and_builds_reproducible_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, paths, run_id, fixture_case, target = _captured_text_fixture(
        tmp_path, monkeypatch
    )
    request = _processing_request(paths, run_id, fixture_case, target)

    result = process_target(request, paths=paths)
    projection = project_terminal_results(
        (request,), (result,), paths=paths, run_id=run_id
    )
    repeated_projection = project_terminal_results(
        (request,), (result,), paths=paths, run_id=run_id
    )
    receipt = read_body_consumption_receipt(paths, run_id, request.target_id)
    assert result.route.value == "text"
    assert projection.fingerprint == repeated_projection.fingerprint
    assert receipt is not None
    assert receipt["processing_run_id"] == result.processing_id
    assert {item.operation_id for item in projection.targets[0].operations} == {
        "raw",
        "text",
        "xml",
    }
    assert {item.status for item in projection.targets[0].operations} == {
        "available",
        "unsupported",
    }
    assert projection.targets[0].operations[0].staged_output_path
    assert (
        projection.targets[0].operations[0].output_sha256
        == hashlib.sha256(_BODY).hexdigest()
    )
    for operation in projection.targets[0].operations:
        if operation.staged_output_path is not None:
            staged_path = paths.run_dir(run_id) / operation.staged_output_path
            assert staged_path.is_relative_to(paths.run_staging_root(run_id))
            assert file_sha256(staged_path) == operation.output_sha256

    artifact_path = tmp_path / "case-artifacts" / "processing-review.json"
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
    assert text_operation["handler_id"] == "text_passthrough"
    assert text_operation["handler_version"] == "1"
    assert text_operation["output_sha256"] == request.body.sha256

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


def test_process_target_rejects_family_disallowed_operation(
    tmp_path: Path,
) -> None:
    from tests.pipelines.document_acquisition.test_processing import _acquired_request

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
