import sqlite3

import pytest

from edgar_sec.pipelines.document_acquisition.models import (
    AcquisitionAttempt,
    AcquisitionOutcome,
)
from edgar_sec.pipelines.document_acquisition.run_state.locks import RunLock
from edgar_sec.pipelines.document_acquisition.run_state.mutations import (
    append_attempt_and_update_target,
    initialize_run_state,
)
from edgar_sec.pipelines.document_acquisition.run_state.queries import (
    get_attempt,
    inspect_run_state,
    summarize_target_state,
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


def _commit(database, attempt: AcquisitionAttempt) -> None:
    append_attempt_and_update_target(
        database,
        attempt,
        _outcome(attempt),
    )


def test_get_attempt_returns_exact_typed_attempt(tmp_path) -> None:
    database = tmp_path / "state.sqlite"
    initialize_run_state(
        database,
        [{"target_id": "target", "executable": True, "skip_reason": None}],
    )
    expected = _attempt("target", "attempt-1", 1, "acquired")
    _commit(database, expected)

    actual = get_attempt(database, "target", "attempt-1")

    assert isinstance(actual, AcquisitionAttempt)
    assert actual == expected


@pytest.mark.parametrize(
    ("target_id", "attempt_id"),
    [
        ("missing-target", "attempt-1"),
        ("target", "missing-attempt"),
        ("other-target", "attempt-1"),
    ],
)
def test_get_attempt_returns_none_for_unknown_or_mismatched_identity(
    tmp_path, target_id, attempt_id
) -> None:
    database = tmp_path / "state.sqlite"
    initialize_run_state(
        database,
        [
            {"target_id": "target", "executable": True, "skip_reason": None},
            {"target_id": "other-target", "executable": True, "skip_reason": None},
        ],
    )
    _commit(database, _attempt("target", "attempt-1", 1, "acquired"))

    assert get_attempt(database, target_id, attempt_id) is None


def test_get_attempt_does_not_mutate_database(tmp_path) -> None:
    database = tmp_path / "state.sqlite"
    initialize_run_state(
        database,
        [{"target_id": "target", "executable": True, "skip_reason": None}],
    )
    expected = _attempt("target", "attempt-1", 1, "acquired")
    _commit(database, expected)
    before = database.read_bytes()

    assert get_attempt(database, "target", "attempt-1") == expected
    assert database.read_bytes() == before


def test_summary_uses_read_only_connection_during_writer_transaction(tmp_path) -> None:
    database = tmp_path / "state.sqlite"
    initialize_run_state(
        database,
        [{"target_id": "target", "executable": True, "skip_reason": None}],
    )
    writer = sqlite3.connect(database)
    writer.execute("BEGIN IMMEDIATE")
    try:
        summary = summarize_target_state(database)
    finally:
        writer.rollback()
        writer.close()
    assert summary.target_counts["pending"] == 1


def test_run_state_derivation_covers_lock_interruption_retry_and_completion(
    tmp_path,
) -> None:
    database = tmp_path / "state.sqlite"
    lock_path = tmp_path / "run.lock"
    initialize_run_state(
        database,
        [
            {"target_id": "first", "executable": True, "skip_reason": None},
            {"target_id": "second", "executable": True, "skip_reason": None},
        ],
    )
    assert (
        inspect_run_state("run", database_path=database, lock_path=lock_path).state
        == "ready"
    )
    lock = RunLock(lock_path, "run")
    assert (
        inspect_run_state("run", database_path=database, lock_path=lock_path).state
        == "running"
    )
    lock.close()

    _commit(database, _attempt("first", "attempt-1", 1, "acquired"))
    assert (
        inspect_run_state("run", database_path=database, lock_path=lock_path).state
        == "interrupted"
    )
    _commit(database, _attempt("second", "attempt-2", 1, "failed", retryable=True))
    assert (
        inspect_run_state("run", database_path=database, lock_path=lock_path).state
        == "needs_retry"
    )


def test_run_state_complete_and_required_missing_are_distinguished(tmp_path) -> None:
    database = tmp_path / "state.sqlite"
    lock_path = tmp_path / "run.lock"
    initialize_run_state(
        database,
        [{"target_id": "target", "executable": True, "skip_reason": None}],
    )
    _commit(database, _attempt("target", "attempt", 1, "required_missing"))
    report = inspect_run_state("run", database_path=database, lock_path=lock_path)
    assert report.state == "complete_with_errors"
    assert report.target_counts["required_missing"] == 1

    complete_database = tmp_path / "complete.sqlite"
    initialize_run_state(
        complete_database,
        [{"target_id": "target", "executable": True, "skip_reason": None}],
    )
    _commit(complete_database, _attempt("target", "attempt", 1, "acquired"))
    assert (
        inspect_run_state(
            "run", database_path=complete_database, lock_path=lock_path
        ).state
        == "complete"
    )


def test_run_state_inspection_reports_invalid_database_without_repair(tmp_path) -> None:
    database = tmp_path / "invalid.sqlite"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA user_version = 1")
    report = inspect_run_state(
        "run", database_path=database, lock_path=tmp_path / "run.lock"
    )
    assert report.state == "invalid"
    assert report.invalid_reason == "unsupported run-state schema version"
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1


def test_run_state_inspection_rejects_lock_for_another_run(tmp_path) -> None:
    database = tmp_path / "state.sqlite"
    initialize_run_state(database, [])
    lock_path = tmp_path / "run.lock"
    lock = RunLock(lock_path, "different-run")
    report = inspect_run_state("run", database_path=database, lock_path=lock_path)
    assert report.state == "invalid"
    assert report.invalid_reason == "run lock belongs to a different run"
    lock.close()
