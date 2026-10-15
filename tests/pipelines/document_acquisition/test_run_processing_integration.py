from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from edgar_sec.domain.document.route import DocumentRoute
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.pipelines.document_acquisition import cli
from edgar_sec.pipelines.document_acquisition.body_handoff import (
    read_body_consumption_receipt,
)
from edgar_sec.pipelines.document_acquisition.models import (
    AcquisitionAttempt,
    AcquisitionOutcome,
)
from edgar_sec.pipelines.document_acquisition.processing import run as processing_run
from edgar_sec.pipelines.document_acquisition.processing.io import (
    DEFAULT_PROCESSING_BUDGETS,
    ProcessingBudgetPolicy,
    ProcessingBudgetRegistry,
)
from edgar_sec.pipelines.document_acquisition.processing.worker import process_target
from edgar_sec.pipelines.document_acquisition.run_state.operations import (
    iter_operation_states,
)
from edgar_sec.pipelines.document_acquisition.run_state.store import (
    append_attempt_and_update_target,
    get_target_state,
)
from tests.acquisition_run_fixture import make_acquisition_run


def test_run_cli_processes_previously_acquired_target_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    artifacts_root = tmp_path / "artifacts"
    paths, run_id, target = make_acquisition_run(artifacts_root, lazy=False)
    body = b"<html><body>offline accepted filing body</body></html>"
    relative_path = "staging/selected-body.html"
    body_path = paths.run_dir(run_id) / relative_path
    body_path.parent.mkdir(parents=True, exist_ok=True)
    body_path.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    timestamp = datetime(2026, 10, 12, tzinfo=UTC).isoformat().replace("+00:00", "Z")
    attempt = AcquisitionAttempt(
        attempt_id="offline-process-body-attempt",
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
        started_at_utc=timestamp,
        finished_at_utc=timestamp,
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

    def unexpected_acquisition(*args, **kwargs):
        raise AssertionError("process must not acquire a document")

    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.commands.common.sec_transport_factory",
        unexpected_acquisition,
    )
    exit_code = cli.main(
        [
            "run",
            "--run-id",
            run_id,
            "--artifacts",
            str(artifacts_root),
            "--json",
        ]
    )

    summary = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert summary["processing"]["complete"] is True
    assert summary["processing"]["success"] is True
    assert summary["run_id"] == run_id
    assert summary["processing"]["operation_counts"] == {
        "available": 1,
        "not_requested": 2,
    }

    target_state = get_target_state(paths.run_state_path(run_id), target["target_id"])
    assert target_state is not None
    assert target_state.outcome == "acquired"
    assert target_state.source_sha256 == target_state.selected_sha256 == digest
    assert target_state.source_byte_size == target_state.selected_byte_size == len(body)
    operation_states = tuple(
        iter_operation_states(paths.run_state_path(run_id), target["target_id"])
    )
    assert {state.operation: state.status for state in operation_states} == {
        "raw": "succeeded",
        "render_to_txt": "not_requested",
        "render_to_xml": "not_requested",
    }
    assert (
        next(
            state for state in operation_states if state.operation == "raw"
        ).attempt_count
        == 1
    )

    result_path = (
        paths.run_staging_root(run_id) / "processing" / f"{target['target_id']}.json"
    )
    manifest_text = result_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    assert manifest["source_sha256"] == digest
    result_operations = {
        operation["operation"]: operation for operation in manifest["operations"]
    }
    assert {name: item["status"] for name, item in result_operations.items()} == {
        "raw": "available",
        "render_to_txt": "not_requested",
        "render_to_xml": "not_requested",
    }
    raw_output = result_operations["raw"]["staged_output"]
    assert raw_output is not None
    assert not Path(raw_output["path"]).is_absolute()
    assert raw_output["sha256"] == digest
    assert raw_output["byte_size"] == len(body)
    assert str(artifacts_root) not in manifest_text
    assert body.decode("ascii") not in manifest_text


def test_process_cli_normalizes_text_with_offline_test_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    artifacts_root = tmp_path / "artifacts"
    paths, run_id, target = make_acquisition_run(
        artifacts_root, lazy=False, default_candidates=True
    )
    assert target["target_url"].endswith(".txt")
    body = b"Offline filing text for the processing CLI acceptance.\n"
    relative_path = "staging/selected-body.txt"
    body_path = paths.run_dir(run_id) / relative_path
    body_path.parent.mkdir(parents=True, exist_ok=True)
    body_path.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    timestamp = datetime(2026, 10, 12, tzinfo=UTC).isoformat().replace("+00:00", "Z")
    attempt = AcquisitionAttempt(
        attempt_id="offline-text-body-attempt",
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
        started_at_utc=timestamp,
        finished_at_utc=timestamp,
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

    def unexpected_acquisition(*args, **kwargs):
        raise AssertionError("process must not acquire a document")

    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.commands.common.sec_transport_factory",
        unexpected_acquisition,
    )
    assert DEFAULT_PROCESSING_BUDGETS.policies == ()
    test_budgets = ProcessingBudgetRegistry(
        (
            ProcessingBudgetPolicy(
                budget_version="offline-text-test-v1",
                route=DocumentRoute.TEXT,
                handler_id="normalize_document",
                handler_version="1",
                max_input_bytes=256,
                max_output_bytes=256,
                working_set_reservation_bytes=64,
            ),
        )
    )
    process_calls = []

    def process_with_test_budget(request, *, paths):
        process_calls.append(request)
        return process_target(request, paths=paths, budget_registry=test_budgets)

    monkeypatch.setattr(processing_run, "process_target", process_with_test_budget)

    exit_code = cli.main(
        [
            "run",
            "--run-id",
            run_id,
            "--artifacts",
            str(artifacts_root),
            "--json",
        ]
    )

    summary = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert summary["processing"]["complete"] is True
    assert summary["processing"]["success"] is True
    assert summary["processing"]["operation_counts"] == {
        "available": 2,
        "not_selected": 1,
    }
    assert len(process_calls) == 1
    request_operations = {
        operation.operation: operation for operation in process_calls[0].operations
    }
    assert request_operations["render_to_txt"].requested is True
    assert request_operations["render_to_txt"].support_status == "supported"
    assert request_operations["render_to_xml"].requested is True
    assert request_operations["render_to_xml"].support_status == "unsupported"

    operation_states = tuple(
        iter_operation_states(paths.run_state_path(run_id), target["target_id"])
    )
    state_by_operation = {state.operation: state for state in operation_states}
    assert state_by_operation["raw"].status == "succeeded"
    assert state_by_operation["render_to_txt"].status == "succeeded"
    assert state_by_operation["render_to_txt"].selected is True
    assert state_by_operation["render_to_txt"].support_status == "supported"
    assert state_by_operation["render_to_txt"].request_mode == "default_candidate"
    assert state_by_operation["render_to_xml"].status == "not_selected"
    assert state_by_operation["render_to_xml"].support_status == "unsupported"
    assert state_by_operation["render_to_xml"].selected is False

    result_path = (
        paths.run_staging_root(run_id) / "processing" / f"{target['target_id']}.json"
    )
    manifest = json.loads(result_path.read_text(encoding="utf-8"))
    result_operations = {
        operation["operation"]: operation for operation in manifest["operations"]
    }
    assert result_operations["raw"]["status"] == "available"
    assert result_operations["render_to_txt"]["status"] == "available"
    assert result_operations["render_to_xml"]["status"] == "unsupported"
    text_output = result_operations["render_to_txt"]["staged_output"]
    assert text_output is not None
    assert text_output["representation"] == "text_normalized"
    assert not Path(text_output["path"]).is_absolute()
    staged_text_path = paths.run_staging_root(run_id) / text_output["path"]
    assert staged_text_path.resolve().is_relative_to(paths.run_dir(run_id).resolve())
    assert file_sha256(staged_text_path) == text_output["sha256"]
    assert staged_text_path.stat().st_size == text_output["byte_size"]
    receipt = read_body_consumption_receipt(paths, run_id, target["target_id"])
    assert receipt is not None
    assert receipt["run_id"] == run_id
    assert receipt["target_id"] == target["target_id"]
    assert receipt["source_response_sha256"] == digest
    assert receipt["selected_sha256"] == digest
    assert receipt["processing_run_id"] == manifest["processing_id"]
    assert DEFAULT_PROCESSING_BUDGETS.policies == ()


def test_run_cli_processes_target_with_production_budgets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    artifacts_root = tmp_path / "artifacts"
    paths, run_id, target = make_acquisition_run(
        artifacts_root, lazy=False, default_candidates=True
    )
    body = b"<html><body><p>Production normalized filing prose.</p></body></html>"
    relative_path = "staging/selected-body.html"
    body_path = paths.run_dir(run_id) / relative_path
    body_path.parent.mkdir(parents=True, exist_ok=True)
    body_path.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    timestamp = datetime(2026, 10, 12, tzinfo=UTC).isoformat().replace("+00:00", "Z")
    attempt = AcquisitionAttempt(
        attempt_id="prod-process-body-attempt",
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
        started_at_utc=timestamp,
        finished_at_utc=timestamp,
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

    def unexpected_acquisition(*args, **kwargs):
        raise AssertionError("process must not acquire a document")

    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.commands.common.sec_transport_factory",
        unexpected_acquisition,
    )

    exit_code = cli.main(
        [
            "run",
            "--run-id",
            run_id,
            "--artifacts",
            str(artifacts_root),
            "--json",
        ]
    )

    summary = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert summary["processing"]["complete"] is True
    assert summary["processing"]["success"] is True

    result_path = (
        paths.run_staging_root(run_id) / "processing" / f"{target['target_id']}.json"
    )
    manifest = json.loads(result_path.read_text(encoding="utf-8"))
    result_operations = {
        operation["operation"]: operation for operation in manifest["operations"]
    }
    assert result_operations["raw"]["status"] == "available"
    assert result_operations["render_to_txt"]["status"] == "available"
    text_output = result_operations["render_to_txt"]["staged_output"]
    assert text_output is not None
    assert text_output["representation"] == "text_normalized"
    staged_text_path = paths.run_staging_root(run_id) / text_output["path"]
    assert staged_text_path.is_file()
    assert "Production normalized filing prose." in staged_text_path.read_text(
        encoding="utf-8"
    )
    assert file_sha256(staged_text_path) == text_output["sha256"]


def test_run_cli_processes_form4_with_production_budgets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    artifacts_root = tmp_path / "artifacts"
    paths, run_id, target = make_acquisition_run(
        artifacts_root,
        lazy=False,
        default_candidates=True,
        form="4",
        filename="nbr59.xml",
    )
    body = (
        b'<?xml version="1.0"?><ownershipDocument><schemaVersion>X0206</schemaVersion>'
        b"<documentType>4</documentType><periodOfReport>2020-01-30</periodOfReport>"
        b"</ownershipDocument>"
    )
    relative_path = "staging/selected-body.xml"
    body_path = paths.run_dir(run_id) / relative_path
    body_path.parent.mkdir(parents=True, exist_ok=True)
    body_path.write_bytes(body)
    digest = hashlib.sha256(body).hexdigest()
    timestamp = datetime(2026, 10, 12, tzinfo=UTC).isoformat().replace("+00:00", "Z")
    attempt = AcquisitionAttempt(
        attempt_id="prod-process-form4-attempt",
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
        started_at_utc=timestamp,
        finished_at_utc=timestamp,
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

    def unexpected_acquisition(*args, **kwargs):
        raise AssertionError("process must not acquire a document")

    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.commands.common.sec_transport_factory",
        unexpected_acquisition,
    )

    exit_code = cli.main(
        [
            "run",
            "--run-id",
            run_id,
            "--artifacts",
            str(artifacts_root),
            "--json",
        ]
    )

    summary = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert summary["processing"]["complete"] is True
    assert summary["processing"]["success"] is True

    result_path = (
        paths.run_staging_root(run_id) / "processing" / f"{target['target_id']}.json"
    )
    manifest = json.loads(result_path.read_text(encoding="utf-8"))
    result_operations = {
        operation["operation"]: operation for operation in manifest["operations"]
    }
    assert result_operations["raw"]["status"] == "available"
    assert result_operations["render_to_xml"]["status"] == "available"
    xml_output = result_operations["render_to_xml"]["staged_output"]
    assert xml_output is not None
    assert xml_output["representation"] == "xml"
    staged_xml_path = paths.run_staging_root(run_id) / xml_output["path"]
    assert staged_xml_path.is_file()
    assert b"<ownershipDocument>" in staged_xml_path.read_bytes()
    assert file_sha256(staged_xml_path) == xml_output["sha256"]
