from __future__ import annotations

import pytest

from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.pipelines.document_acquisition.models import (
    AcquisitionAttempt,
    AcquisitionOutcome,
    OperationAttempt,
)
from edgar_sec.pipelines.document_acquisition.plan_projection.operation_resolution import (
    resolve_operation_group,
)
from edgar_sec.pipelines.document_acquisition.run_state.models import (
    WorkOrderOperationSeed,
    WorkOrderTargetSeed,
)
from edgar_sec.pipelines.document_acquisition.run_state.operations import (
    append_operation_attempt,
    get_operation_state,
    iter_operation_states,
    list_operation_attempts,
    operation_attempt_id,
)
from edgar_sec.pipelines.document_acquisition.run_state.store import (
    RunStateError,
    append_attempt_and_update_target,
    get_target_state,
    initialize_run_state,
    validate_run_state,
)


def _operation() -> WorkOrderOperationSeed:
    target_id = "target-1"
    name = "render_to_txt"
    return WorkOrderOperationSeed(
        operation_id=canonical_hash([target_id, name]),
        target_id=target_id,
        operation=name,
        requested=True,
        request_mode="profile",
        selected=True,
        source_request_id="source-1",
        input_ordinal=0,
        input_role="selected_target_body",
        support_status="supported",
        support_reason=None,
        capability_id="text.markup",
        capability_version="1",
        handler_id="normalize_document",
        handler_version="1",
        output_kind="text",
    )


def _resolved_operations(xml_mode: str) -> list[WorkOrderOperationSeed]:
    target_id = "target-1"
    target = {
        "target_id": target_id,
        "form": "10-K",
        "target_role": "primary",
        "target_type": "primary",
    }
    modes = {
        "raw": "mandatory_raw",
        "render_to_txt": "default_candidate",
        "render_to_xml": xml_mode,
    }
    intents = [
        {
            "operation_id": canonical_hash([target_id, operation]),
            "target_id": target_id,
            "operation": operation,
            "requested": mode != "not_requested",
            "request_mode": mode,
        }
        for operation, mode in modes.items()
    ]
    source = {
        "source_request_id": "source-1",
        "canonical_path": "primary-document.htm",
    }
    inputs = [
        {
            "operation_id": intent["operation_id"],
            "input_ordinal": 0,
            "source_request_id": "source-1",
            "input_role": "selected_target_body",
        }
        for intent in intents
        if intent["requested"]
    ]
    return [
        WorkOrderOperationSeed(**row)
        for row in resolve_operation_group(target, intents, source, inputs)
    ]


def _acquire_target(database):
    attempt = AcquisitionAttempt(
        attempt_id="target-attempt-1",
        target_id="target-1",
        attempt_number=1,
        attempt_kind="document_body",
        source="live_sec",
        requested_url="https://www.sec.gov/Archives/body.htm",
        outcome="acquired",
        retryable=False,
        error_code=None,
        http_status=200,
        final_url="https://www.sec.gov/Archives/body.htm",
        started_at_utc="2026-01-01T00:00:00Z",
        finished_at_utc="2026-01-01T00:00:01Z",
        source_sha256="a" * 64,
        source_byte_size=1,
        source_body_relative_path="staging/source.bin",
        selected_sha256="a" * 64,
        selected_byte_size=1,
        selected_body_relative_path="staging/selected.bin",
    )
    outcome = AcquisitionOutcome(
        target_id="target-1",
        source="live_sec",
        status="acquired",
        attempt_count=1,
        last_attempt_id=attempt.attempt_id,
        error_code=None,
        retryable=False,
        source_sha256=attempt.source_sha256,
        source_byte_size=attempt.source_byte_size,
        source_body_relative_path=attempt.source_body_relative_path,
        selected_sha256=attempt.selected_sha256,
        selected_byte_size=attempt.selected_byte_size,
        body_lifecycle="staged",
        selected_body_relative_path=attempt.selected_body_relative_path,
    )
    append_attempt_and_update_target(database, attempt, outcome)


def _attempt(
    operation_id: str, number: int, outcome: str, retryable: bool, error: str | None
) -> OperationAttempt:
    return OperationAttempt(
        attempt_id=operation_attempt_id(operation_id, number),
        operation_id=operation_id,
        attempt_number=number,
        outcome=outcome,
        retryable=retryable,
        error_code=error,
        started_at_utc=f"2026-01-01T00:00:0{number}Z",
        finished_at_utc=f"2026-01-01T00:00:1{number}Z",
    )


def test_operation_attempts_have_independent_identity_and_failure(tmp_path):
    database = tmp_path / "run.sqlite"
    operation = _operation()
    initialize_run_state(
        database,
        [WorkOrderTargetSeed("target-1", True, None)],
        [operation],
    )
    assert get_operation_state(database, operation.operation_id).status == "blocked"
    _acquire_target(database)
    assert get_operation_state(database, operation.operation_id).status == "pending"

    failed = _attempt(operation.operation_id, 1, "failed", True, "render_error")
    append_operation_attempt(database, failed)

    state = get_operation_state(database, operation.operation_id)
    assert state is not None
    assert (state.status, state.attempt_count, state.last_attempt_id) == (
        "failed",
        1,
        failed.attempt_id,
    )
    target_state = get_target_state(database, operation.target_id)
    assert (target_state.outcome, target_state.attempt_count) == ("acquired", 1)
    assert list_operation_attempts(database, operation.operation_id) == (failed,)

    succeeded = _attempt(operation.operation_id, 2, "succeeded", False, None)
    append_operation_attempt(database, succeeded)
    history = list_operation_attempts(database, operation.operation_id)
    assert [attempt.attempt_number for attempt in history] == [1, 2]
    assert history[0].attempt_id != history[1].attempt_id
    assert get_operation_state(database, operation.operation_id).status == "succeeded"
    assert get_target_state(database, operation.target_id).attempt_count == 1
    assert tuple(iter_operation_states(database, operation.target_id)) == (
        get_operation_state(database, operation.operation_id),
    )


def test_operation_attempt_identity_must_match_sequence(tmp_path):
    database = tmp_path / "run.sqlite"
    operation = _operation()
    initialize_run_state(
        database,
        [WorkOrderTargetSeed("target-1", True, None)],
        [operation],
    )
    _acquire_target(database)
    attempt = _attempt(operation.operation_id, 1, "failed", False, "render_error")
    malformed = OperationAttempt(
        attempt_id="not-the-operation-attempt-id",
        operation_id=attempt.operation_id,
        attempt_number=attempt.attempt_number,
        outcome=attempt.outcome,
        retryable=attempt.retryable,
        error_code=attempt.error_code,
        started_at_utc=attempt.started_at_utc,
        finished_at_utc=attempt.finished_at_utc,
    )
    with pytest.raises(ValueError, match="identity"):
        append_operation_attempt(database, malformed)
    with pytest.raises(RunStateError, match="next attempt"):
        append_operation_attempt(
            database,
            _attempt(operation.operation_id, 2, "failed", False, "render_error"),
        )
    assert list_operation_attempts(database, operation.operation_id) == ()


def test_unsupported_default_candidate_is_terminal_not_selected(tmp_path):
    database = tmp_path / "run.sqlite"
    operations = _resolved_operations("default_candidate")
    initialize_run_state(
        database,
        [WorkOrderTargetSeed("target-1", True, None)],
        operations,
    )

    validate_run_state(database)
    text = next(
        operation for operation in operations if operation.operation == "render_to_txt"
    )
    assert text.selected
    assert text.support_status == "supported"
    assert get_operation_state(database, text.operation_id).status == "blocked"
    xml = next(
        operation for operation in operations if operation.operation == "render_to_xml"
    )
    xml_state = get_operation_state(database, xml.operation_id)
    assert xml_state is not None
    assert xml_state.status == "not_selected"
    assert xml_state.support_status == "unsupported"
    assert list_operation_attempts(database, xml.operation_id) == ()
    assert (
        sum(state.status == "unsupported" for state in iter_operation_states(database))
        == 0
    )


def test_unsupported_explicit_profile_operation_remains_unsupported(tmp_path):
    database = tmp_path / "run.sqlite"
    operations = _resolved_operations("profile")
    initialize_run_state(
        database,
        [WorkOrderTargetSeed("target-1", True, None)],
        operations,
    )

    validate_run_state(database)
    explicit_xml = next(
        operation for operation in operations if operation.operation == "render_to_xml"
    )
    state = get_operation_state(database, explicit_xml.operation_id)
    assert state is not None
    assert state.status == "unsupported"
    assert state.support_status == "unsupported"
    assert list_operation_attempts(database, explicit_xml.operation_id) == ()
