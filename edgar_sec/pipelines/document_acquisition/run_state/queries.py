from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path

from edgar_sec.pipelines.document_acquisition.models import (
    AcquisitionAttempt,
    AcquisitionStatusCounts,
    AcquisitionStatusReport,
    RunStatus,
)
from edgar_sec.pipelines.document_acquisition.run_state.locks import (
    RunLockError,
    inspect_run_lock,
)
from edgar_sec.pipelines.document_acquisition.run_state.models import (
    TargetState,
    _acquisition_attempt_from_row,
    _target_state_from_row,
)
from edgar_sec.pipelines.document_acquisition.run_state.operations import (
    validate_operation_state,
)
from edgar_sec.pipelines.document_acquisition.run_state.schema import (
    _COUNT_ATTEMPTED,
    _COUNT_OUTCOMES,
    _COUNT_RETRYABLE,
    _GET_ATTEMPT,
    _GET_TARGET,
    _OUTCOMES,
    _SELECT_PENDING,
    _SELECT_RETRY,
)
from edgar_sec.pipelines.document_acquisition.run_state.store import (
    RunStateError,
    _connect,
    _require_schema,
)


def iter_selected_target_states(
    database_path: Path, *, retry_failures: bool = False
) -> Iterator[TargetState]:
    connection = _connect(Path(database_path), readonly=True)
    try:
        _require_schema(connection)
        statement = _SELECT_RETRY if retry_failures else _SELECT_PENDING
        cursor = connection.execute(statement)
        try:
            for row in cursor:
                yield _target_state_from_row(row)
        finally:
            cursor.close()
    finally:
        connection.close()


def get_attempt(
    database_path: Path, target_id: str, attempt_id: str
) -> AcquisitionAttempt | None:
    connection = _connect(Path(database_path), readonly=True)
    try:
        _require_schema(connection)
        row = connection.execute(_GET_ATTEMPT, (target_id, attempt_id)).fetchone()
        if row is None:
            return None
        attempt = _acquisition_attempt_from_row(row)
        if attempt.target_id != target_id or attempt.attempt_id != attempt_id:
            return None
        return attempt
    finally:
        connection.close()


def get_target_state(database_path: Path, target_id: str) -> TargetState | None:
    connection = _connect(Path(database_path), readonly=True)
    try:
        _require_schema(connection)
        row = connection.execute(_GET_TARGET, (target_id,)).fetchone()
        return None if row is None else _target_state_from_row(row)
    finally:
        connection.close()


def iter_target_state_pairs(
    database_path: Path, targets: Iterable[Mapping[str, object]]
) -> Iterator[tuple[Mapping[str, object], TargetState | None]]:
    connection = _connect(Path(database_path), readonly=True)
    try:
        _require_schema(connection)
        for target in targets:
            target_id = str(target["target_id"])
            row = connection.execute(_GET_TARGET, (target_id,)).fetchone()
            state = None if row is None else _target_state_from_row(row)
            yield target, state
    finally:
        connection.close()


def _validate_readonly(connection: sqlite3.Connection) -> None:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    foreign_key_error = connection.execute("PRAGMA foreign_key_check").fetchone()
    if integrity != "ok" or foreign_key_error is not None:
        raise RunStateError(
            f"integrity_check={integrity!r}; foreign_key_check={foreign_key_error!r}"
        )
    validate_operation_state(connection)


def summarize_target_state(database_path: Path) -> AcquisitionStatusCounts:
    connection = _connect(Path(database_path), readonly=True)
    try:
        _require_schema(connection)
        _validate_readonly(connection)
        counts = {status: 0 for status in _OUTCOMES}
        for status, count in connection.execute(_COUNT_OUTCOMES):
            counts[status] = count
        retryable = connection.execute(_COUNT_RETRYABLE, ("failed", 1)).fetchone()[0]
        non_retryable = connection.execute(_COUNT_RETRYABLE, ("failed", 0)).fetchone()[
            0
        ]
        return AcquisitionStatusCounts(
            target_counts=counts,
            retryable_failure_count=retryable,
            non_retryable_failure_count=non_retryable,
        )
    finally:
        connection.close()


def validate_run_state(database_path: Path) -> None:
    connection = _connect(Path(database_path), readonly=True)
    try:
        _require_schema(connection)
        _validate_readonly(connection)
    finally:
        connection.close()


def inspect_run_state(
    run_id: str,
    *,
    database_path: Path,
    lock_path: Path,
) -> AcquisitionStatusReport:
    empty_counts = {status: 0 for status in _OUTCOMES}
    active_lock = None
    try:
        active_lock = inspect_run_lock(Path(lock_path), expected_run_id=run_id)
        counts = summarize_target_state(database_path)
        connection = _connect(Path(database_path), readonly=True)
        try:
            _require_schema(connection)
            attempted_count = connection.execute(_COUNT_ATTEMPTED).fetchone()[0]
        finally:
            connection.close()
    except (OSError, sqlite3.Error, RunLockError, RunStateError, ValueError) as error:
        return AcquisitionStatusReport(
            run_id=run_id,
            state="invalid",
            target_counts=empty_counts,
            retryable_failure_count=0,
            non_retryable_failure_count=0,
            active_lock=active_lock,
            invalid_reason=str(error),
        )
    if active_lock is not None:
        state: RunStatus = "running"
    elif counts.target_counts["pending"] and attempted_count:
        state = "interrupted"
    elif counts.retryable_failure_count:
        state = "needs_retry"
    elif counts.non_retryable_failure_count or counts.target_counts["required_missing"]:
        state = "complete_with_errors"
    elif attempted_count == 0:
        state = "ready"
    else:
        state = "complete"
    return AcquisitionStatusReport(
        run_id=run_id,
        state=state,
        target_counts=counts.target_counts,
        retryable_failure_count=counts.retryable_failure_count,
        non_retryable_failure_count=counts.non_retryable_failure_count,
        active_lock=active_lock,
        invalid_reason=None,
    )


__all__ = [
    "get_attempt",
    "get_target_state",
    "inspect_run_state",
    "iter_selected_target_states",
    "iter_target_state_pairs",
    "summarize_target_state",
    "validate_run_state",
]
