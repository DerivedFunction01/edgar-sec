from dataclasses import replace

from edgar_sec.pipelines.document_acquisition.models import (
    AcquisitionAttempt,
    AcquisitionOutcome,
    TargetSlotResolution,
)
from edgar_sec.pipelines.document_acquisition.run_state.evidence import (
    get_attempt_evidence_group,
    list_target_attempts,
)
from edgar_sec.pipelines.document_acquisition.run_state.models import (
    AttemptEvidenceGroup,
)
from edgar_sec.pipelines.document_acquisition.run_state.store import (
    append_attempt_and_update_target,
    commit_attempts_and_update_target,
    initialize_run_state,
)


def _attempt(
    target_id: str,
    attempt_id: str,
    number: int,
    status: str,
    *,
    retryable: bool = False,
) -> AcquisitionAttempt:
    acquired = status == "acquired"
    return AcquisitionAttempt(
        attempt_id=attempt_id,
        target_id=target_id,
        attempt_number=number,
        attempt_kind="document_body",
        source="live_sec",
        requested_url="https://www.sec.gov/Archives/requested.htm",
        outcome=status,
        retryable=retryable,
        error_code=None if acquired else "transport_error",
        http_status=200 if acquired else None,
        final_url="https://www.sec.gov/Archives/document.htm" if acquired else None,
        started_at_utc="2025-01-01T00:00:00Z",
        finished_at_utc="2025-01-01T00:00:01Z",
        source_sha256="a" * 64 if acquired else None,
        source_byte_size=5 if acquired else None,
        source_body_relative_path="staging/source.bin" if acquired else None,
        selected_sha256="b" * 64 if acquired else None,
        selected_byte_size=5 if acquired else None,
        selected_body_relative_path="staging/selected.bin" if acquired else None,
    )


def _outcome(attempt: AcquisitionAttempt) -> AcquisitionOutcome:
    acquired = attempt.outcome == "acquired"
    return AcquisitionOutcome(
        target_id=attempt.target_id,
        source=attempt.source,
        status=attempt.outcome,
        attempt_count=attempt.attempt_number,
        last_attempt_id=attempt.attempt_id,
        error_code=attempt.error_code,
        retryable=attempt.retryable,
        source_sha256=attempt.source_sha256,
        source_byte_size=attempt.source_byte_size,
        source_body_relative_path=attempt.source_body_relative_path,
        selected_sha256=attempt.selected_sha256,
        selected_byte_size=attempt.selected_byte_size,
        body_lifecycle="staged" if acquired else None,
        selected_body_relative_path=attempt.selected_body_relative_path,
    )


def _commit_lazy_group(database, *, index_status="acquired", selected=True):
    initialize_run_state(
        database,
        [{"target_id": "target", "executable": True, "skip_reason": None}],
    )
    initial = _attempt("target", "initial", 1, "acquired")
    index = replace(
        _attempt("target", "index", 2, index_status),
        attempt_kind="lazy_index",
        requested_url="https://www.sec.gov/Archives/index.html",
        source_sha256=None,
        source_byte_size=None,
        source_body_relative_path=None,
        selected_sha256=None,
        selected_byte_size=None,
        selected_body_relative_path=None,
    )
    selected_attempt = None
    if selected:
        selected_attempt = replace(
            _attempt("target", "selected", 3, "acquired"),
            requested_url="https://www.sec.gov/Archives/selected.htm",
        )
    resolution = TargetSlotResolution(
        resolution_schema_version="1",
        resolution_id="resolution",
        run_id="run",
        target_id="target",
        target_role="primary",
        target_type="primary",
        selector="exact_form_with_lazy_index",
        expected_statutory_type="10-K",
        initial_sequence=1,
        index_document_type="10-K" if selected else None,
        index_primary_designation=None,
        initial_observed_body_type=None,
        screen_kind="html_cover",
        screen_result="unverifiable",
        evaluator_version=None,
        initial_body_sha256=initial.source_sha256,
        index_attempt_id=index.attempt_id,
        index_response_sha256="d" * 64 if index_status == "acquired" else None,
        index_parser_version="parser-v1",
        matching_entry_ids=("entry-1",) if selected else (),
        selected_sequence=2 if selected else None,
        selected_retrieval_mode="direct_url" if selected else None,
        selected_url=selected_attempt.requested_url if selected_attempt else None,
        result="recovered" if selected else "failed",
    )
    attempts = (
        (initial, index, selected_attempt) if selected_attempt else (initial, index)
    )
    final_attempt = attempts[-1]
    outcome = replace(
        _outcome(final_attempt),
        attempt_count=final_attempt.attempt_number,
        last_attempt_id=final_attempt.attempt_id,
    )
    commit_attempts_and_update_target(
        database,
        attempts,
        outcome,
        resolution=resolution,
        recorded_at_utc="2025-01-01T00:00:02Z",
    )
    return initial, index, selected_attempt, resolution


def test_get_attempt_evidence_group_returns_direct_only_attempt(tmp_path) -> None:
    database = tmp_path / "state.sqlite"
    initialize_run_state(
        database,
        [{"target_id": "target", "executable": True, "skip_reason": None}],
    )
    initial = _attempt("target", "initial", 1, "acquired")
    append_attempt_and_update_target(database, initial, _outcome(initial))

    group = get_attempt_evidence_group(database, "target", "initial")

    assert group == AttemptEvidenceGroup(initial, None, None, None)


def test_get_attempt_evidence_group_returns_successful_lazy_group(tmp_path) -> None:
    database = tmp_path / "state.sqlite"
    initial, index, selected, expected_resolution = _commit_lazy_group(database)

    group = get_attempt_evidence_group(database, "target", "initial")

    assert isinstance(group, AttemptEvidenceGroup)
    assert group.initial_attempt == initial
    assert group.lazy_index_attempt == index
    assert group.selected_body_attempt == selected
    assert group.resolution is not None
    assert group.resolution.resolution_id == expected_resolution.resolution_id
    assert group.resolution.matching_entry_ids == ("entry-1",)
    assert group.resolution.initial_body_sha256 == initial.source_sha256
    assert group.resolution.selected_url == selected.requested_url
    assert group.resolution.run_id is None
    assert group.resolution.target_role is None


def test_get_attempt_evidence_group_keeps_failed_index_without_selected_body(
    tmp_path,
) -> None:
    database = tmp_path / "state.sqlite"
    initial, index, selected, _ = _commit_lazy_group(
        database, index_status="failed", selected=False
    )

    group = get_attempt_evidence_group(database, "target", "initial")

    assert group is not None
    assert group.initial_attempt == initial
    assert group.lazy_index_attempt == index
    assert group.selected_body_attempt is None
    assert group.resolution is not None
    assert group.resolution.result == "failed"
    assert selected is None


def test_get_attempt_evidence_group_returns_none_for_unknown_initial_id(
    tmp_path,
) -> None:
    database = tmp_path / "state.sqlite"
    initialize_run_state(
        database,
        [{"target_id": "target", "executable": True, "skip_reason": None}],
    )

    assert get_attempt_evidence_group(database, "target", "missing") is None
    assert get_attempt_evidence_group(database, "missing-target", "missing") is None


def test_get_attempt_evidence_group_does_not_mutate_database(tmp_path) -> None:
    database = tmp_path / "state.sqlite"
    initial, _, _, _ = _commit_lazy_group(database)
    before = database.read_bytes()

    assert (
        get_attempt_evidence_group(database, "target", initial.attempt_id) is not None
    )
    assert database.read_bytes() == before


def test_list_target_attempts_orders_by_attempt_number(tmp_path) -> None:
    database = tmp_path / "state.sqlite"
    initialize_run_state(
        database,
        [
            {"target_id": "target", "executable": True, "skip_reason": None},
            {"target_id": "other", "executable": True, "skip_reason": None},
        ],
    )
    first = _attempt("target", "z-first", 1, "failed", retryable=True)
    second = _attempt("target", "a-second", 2, "acquired")
    other = _attempt("other", "other-first", 1, "acquired")
    append_attempt_and_update_target(database, first, _outcome(first))
    append_attempt_and_update_target(database, second, _outcome(second))
    append_attempt_and_update_target(database, other, _outcome(other))

    attempts = list_target_attempts(database, "target")

    assert attempts == [first, second]


def test_list_target_attempts_returns_empty_for_target_without_attempts(
    tmp_path,
) -> None:
    database = tmp_path / "state.sqlite"
    initialize_run_state(
        database,
        [{"target_id": "target", "executable": True, "skip_reason": None}],
    )

    assert list_target_attempts(database, "target") == []
    assert list_target_attempts(database, "missing") == []


def test_list_target_attempts_does_not_mutate_database(tmp_path) -> None:
    database = tmp_path / "state.sqlite"
    initialize_run_state(
        database,
        [{"target_id": "target", "executable": True, "skip_reason": None}],
    )
    attempt = _attempt("target", "attempt-1", 1, "acquired")
    append_attempt_and_update_target(database, attempt, _outcome(attempt))
    before = database.read_bytes()

    assert list_target_attempts(database, "target") == [attempt]
    assert database.read_bytes() == before
