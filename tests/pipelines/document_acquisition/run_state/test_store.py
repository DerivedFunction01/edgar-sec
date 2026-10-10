import sqlite3
from dataclasses import replace
from itertools import chain

import pytest

from edgar_sec.pipelines.document_acquisition.models import (
    AcquisitionAttempt,
    AcquisitionOutcome,
    TargetSlotResolution,
)
from edgar_sec.pipelines.document_acquisition.run_state.locks import RunLock
from edgar_sec.pipelines.document_acquisition.run_state.models import (
    WorkOrderTargetSeed,
)
from edgar_sec.pipelines.document_acquisition.run_state.store import (
    RunStateError,
    append_attempt_and_update_target,
    append_target_slot_resolution,
    commit_attempts_and_update_target,
    get_target_state,
    inspect_run_state,
    initialize_run_state,
    iter_selected_target_states,
    summarize_target_state,
    validate_run_state,
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


def test_initialization_streams_one_transaction_and_duplicate_refuses(tmp_path) -> None:
    database = tmp_path / "state.sqlite"
    targets = (
        {
            "target_id": f"target-{number}",
            "executable": number == 0,
            "skip_reason": None if number == 0 else "target_not_matched",
        }
        for number in range(2)
    )
    initialize_run_state(
        database,
        chain(targets, [WorkOrderTargetSeed("target-2", False, "target_not_matched")]),
    )

    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 0
        assert connection.execute(
            "SELECT target_id, outcome FROM target_state ORDER BY target_id"
        ).fetchall() == [
            ("target-0", "pending"),
            ("target-1", "skipped"),
            ("target-2", "skipped"),
        ]

    with pytest.raises(sqlite3.IntegrityError):
        initialize_run_state(
            database,
            [{"target_id": "target-0", "executable": True, "skip_reason": None}],
        )
    assert summarize_target_state(database).target_counts["pending"] == 1


def test_initialization_rolls_back_stream_failure(tmp_path) -> None:
    database = tmp_path / "state.sqlite"

    def seed():
        yield {"target_id": "first", "executable": True, "skip_reason": None}
        raise RuntimeError("seed interrupted")

    with pytest.raises(RuntimeError, match="seed interrupted"):
        initialize_run_state(database, seed())
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table'"
            ).fetchone()[0]
            == 0
        )


def test_schema_v1_is_refused_and_foreign_keys_are_enabled(tmp_path) -> None:
    old_database = tmp_path / "old.sqlite"
    with sqlite3.connect(old_database) as connection:
        connection.execute("PRAGMA user_version = 1")
    with pytest.raises(RunStateError, match="schema version"):
        initialize_run_state(old_database, [])

    database = tmp_path / "state.sqlite"
    initialize_run_state(
        database,
        [{"target_id": "target", "executable": True, "skip_reason": None}],
    )
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA foreign_keys = ON")
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            "INSERT INTO attempts (attempt_id, target_id, attempt_number, outcome, "
            "attempt_kind, source, retryable, requested_url, started_at_utc, "
            "finished_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "attempt",
                "missing",
                1,
                "failed",
                "document_body",
                "live_sec",
                0,
                "https://www.sec.gov/request",
                "start",
                "finish",
            ),
        )
    connection.close()


def test_retry_commit_is_atomic_and_attempt_history_is_append_only(tmp_path) -> None:
    database = tmp_path / "state.sqlite"
    target_id = "target' OR 1=1 --"
    initialize_run_state(
        database,
        [{"target_id": target_id, "executable": True, "skip_reason": None}],
    )
    failed = _attempt(target_id, "attempt-1", 1, "failed", retryable=True)
    _commit(database, failed)
    assert [state.target_id for state in iter_selected_target_states(database)] == []
    assert [
        state.target_id
        for state in iter_selected_target_states(database, retry_failures=True)
    ] == [target_id]
    assert get_target_state(database, target_id).outcome == "failed"
    assert get_target_state(database, "missing") is None

    acquired = _attempt(target_id, "attempt-2", 2, "acquired")
    _commit(database, acquired)
    summary = summarize_target_state(database)
    assert summary.target_counts["acquired"] == 1
    assert summary.retryable_failure_count == 0
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT attempt_number, outcome FROM attempts ORDER BY attempt_number"
        ).fetchall() == [(1, "failed"), (2, "acquired")]
        assert connection.execute(
            "SELECT attempt_count, last_attempt_id, selected_sha256 FROM target_state "
            "WHERE target_id = ?",
            (target_id,),
        ).fetchone() == (2, "attempt-2", "b" * 64)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "DELETE FROM attempts WHERE attempt_id = ?", ("attempt-1",)
            )
    validate_run_state(database)


def test_attempt_failure_rolls_back_both_history_and_projection(tmp_path) -> None:
    database = tmp_path / "state.sqlite"
    initialize_run_state(
        database,
        [{"target_id": "target", "executable": True, "skip_reason": None}],
    )
    attempt = _attempt("target", "attempt", 1, "acquired")
    wrong_outcome = replace(_outcome(attempt), attempt_count=7)
    with pytest.raises(ValueError, match="projection"):
        append_attempt_and_update_target(
            database,
            attempt,
            wrong_outcome,
        )
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 0
        assert connection.execute(
            "SELECT outcome, attempt_count FROM target_state"
        ).fetchone() == ("pending", 0)


def test_attempt_insert_failure_rolls_back_target_projection(tmp_path) -> None:
    database = tmp_path / "state.sqlite"
    initialize_run_state(
        database,
        [
            {"target_id": "first", "executable": True, "skip_reason": None},
            {"target_id": "second", "executable": True, "skip_reason": None},
        ],
    )
    _commit(database, _attempt("first", "duplicate-id", 1, "failed"))
    with pytest.raises(sqlite3.IntegrityError):
        _commit(database, _attempt("second", "duplicate-id", 1, "acquired"))
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0] == 1
        assert connection.execute(
            "SELECT outcome, attempt_count FROM target_state WHERE target_id = ?",
            ("second",),
        ).fetchone() == ("pending", 0)


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


def test_resolution_history_is_fk_checked_and_append_only(tmp_path) -> None:
    database = tmp_path / "state.sqlite"
    initialize_run_state(
        database,
        [{"target_id": "target", "executable": True, "skip_reason": None}],
    )
    resolution = TargetSlotResolution(
        resolution_schema_version="1",
        resolution_id="resolution-1",
        run_id="run-1",
        target_id="target",
        target_role="primary",
        target_type="primary",
        selector="exact_form_with_lazy_index",
        expected_statutory_type="10-K",
        initial_sequence=1,
        index_document_type=None,
        index_primary_designation=None,
        initial_observed_body_type=None,
        screen_kind="none",
        screen_result="not_run",
        evaluator_version=None,
        initial_body_sha256="a" * 64,
        index_attempt_id=None,
        index_response_sha256=None,
        index_parser_version=None,
        matching_entry_ids=("entry-1", "entry-2"),
        selected_sequence=2,
        selected_retrieval_mode="direct_url",
        selected_url="https://www.sec.gov/Archives/selected.htm",
        result="recovered",
    )
    append_target_slot_resolution(
        database, resolution, recorded_at_utc="2025-01-01T00:00:00Z"
    )
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT matching_entry_ids_json, selected_sequence FROM target_slot_resolutions"
        ).fetchone()
        assert row == ('["entry-1","entry-2"]', 2)
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("UPDATE target_slot_resolutions SET result = 'failed'")


def test_lazy_resolution_commits_all_attempts_and_projection_atomically(
    tmp_path,
) -> None:
    database = tmp_path / "state.sqlite"
    initialize_run_state(
        database,
        [{"target_id": "target", "executable": True, "skip_reason": None}],
    )
    initial = _attempt("target", "initial", 1, "acquired")
    index = replace(
        _attempt("target", "index", 2, "acquired"),
        attempt_kind="lazy_index",
        requested_url="https://www.sec.gov/Archives/edgar/data/320193/000032019320000096/0000320193-20-000096-index.html",
        source_sha256=None,
        source_byte_size=None,
        source_body_relative_path=None,
        selected_sha256=None,
        selected_byte_size=None,
        selected_body_relative_path=None,
    )
    selected = replace(
        _attempt("target", "selected", 3, "acquired"),
        requested_url="https://www.sec.gov/Archives/edgar/data/320193/000032019320000096/report.htm",
    )
    resolution = TargetSlotResolution(
        resolution_schema_version="1",
        resolution_id="lazy-resolution",
        run_id="run-1",
        target_id="target",
        target_role="primary",
        target_type="primary",
        selector="exact_form_with_lazy_index",
        expected_statutory_type="10-K",
        initial_sequence=1,
        index_document_type="10-K",
        index_primary_designation=None,
        initial_observed_body_type=None,
        screen_kind="html_cover",
        screen_result="unverifiable",
        evaluator_version=None,
        initial_body_sha256="c" * 64,
        index_attempt_id="index",
        index_response_sha256="d" * 64,
        index_parser_version="index-page-v1",
        matching_entry_ids=("entry-1",),
        selected_sequence=2,
        selected_retrieval_mode="direct_url",
        selected_url=selected.requested_url,
        result="recovered",
    )
    outcome = replace(
        _outcome(selected),
        attempt_count=3,
        last_attempt_id="selected",
    )

    commit_attempts_and_update_target(
        database,
        (initial, index, selected),
        outcome,
        resolution=resolution,
        recorded_at_utc="2025-01-01T00:00:02Z",
    )

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT attempt_number, attempt_kind FROM attempts ORDER BY attempt_number"
        ).fetchall() == [
            (1, "document_body"),
            (2, "lazy_index"),
            (3, "document_body"),
        ]
        assert connection.execute(
            "SELECT index_attempt_id, result FROM target_slot_resolutions"
        ).fetchone() == ("index", "recovered")
        assert connection.execute(
            "SELECT outcome, attempt_count, last_attempt_id FROM target_state"
        ).fetchone() == ("acquired", 3, "selected")


def test_lazy_resolution_transaction_rolls_back_attempts_on_bad_index_reference(
    tmp_path,
) -> None:
    database = tmp_path / "state.sqlite"
    initialize_run_state(
        database,
        [{"target_id": "target", "executable": True, "skip_reason": None}],
    )
    initial = _attempt("target", "initial", 1, "acquired")
    index = replace(
        _attempt("target", "index", 2, "acquired"),
        attempt_kind="lazy_index",
    )
    resolution = TargetSlotResolution(
        resolution_schema_version="1",
        resolution_id="invalid-resolution",
        run_id="run-1",
        target_id="target",
        target_role="primary",
        target_type="primary",
        selector="exact_form_with_lazy_index",
        expected_statutory_type="10-K",
        initial_sequence=1,
        index_document_type=None,
        index_primary_designation=None,
        initial_observed_body_type=None,
        screen_kind="html_cover",
        screen_result="unverifiable",
        evaluator_version=None,
        initial_body_sha256="c" * 64,
        index_attempt_id="initial",
        index_response_sha256="d" * 64,
        index_parser_version="index-page-v1",
        matching_entry_ids=(),
        selected_sequence=None,
        selected_retrieval_mode=None,
        selected_url=None,
        result="not_filed",
    )
    outcome = replace(
        _outcome(index),
        status="not_filed",
        attempt_count=2,
        last_attempt_id="index",
        source_sha256="c" * 64,
        source_byte_size=5,
    )

    with pytest.raises(ValueError, match="index attempt is missing or mismatched"):
        commit_attempts_and_update_target(
            database,
            (initial, index),
            outcome,
            resolution=resolution,
            recorded_at_utc="2025-01-01T00:00:02Z",
        )

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM attempts").fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM target_slot_resolutions"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT outcome, attempt_count FROM target_state"
        ).fetchone() == ("pending", 0)


@pytest.mark.parametrize(
    "requested_url",
    [
        "https://user@www.sec.gov/document",
        "https://www.sec.gov/document?token=secret",
        "https://www.sec.gov/document#fragment",
    ],
)
def test_attempt_rejects_non_exact_requested_urls(tmp_path, requested_url) -> None:
    database = tmp_path / "state.sqlite"
    initialize_run_state(
        database,
        [{"target_id": "target", "executable": True, "skip_reason": None}],
    )
    attempt = _attempt("target", "attempt", 1, "failed", retryable=True)
    attempt = replace(attempt, requested_url=requested_url)
    with pytest.raises(ValueError, match="requested_url"):
        append_attempt_and_update_target(
            database,
            attempt,
            _outcome(attempt),
        )
