from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from urllib.parse import quote, urlsplit

from edgar_sec.pipelines.document_acquisition.models import (
    AcquisitionAttempt,
    AcquisitionOutcome,
    AcquisitionStatusCounts,
    AcquisitionStatusReport,
    RunStatus,
    TargetSlotResolution,
)
from edgar_sec.pipelines.document_acquisition.run_state.models import (
    TargetState,
    WorkOrderTargetSeed,
    _acquisition_attempt_from_row,
    _target_state_from_row,
)
from edgar_sec.pipelines.document_acquisition.run_state.locks import (
    RunLockError,
    inspect_run_lock,
)
from edgar_sec.infra.storage.duckdb import sql_literal

SCHEMA_VERSION = 2
_OUTCOMES = (
    "pending",
    "skipped",
    "acquired",
    "not_filed",
    "required_missing",
    "ambiguous",
    "failed",
)
_SCHEMA = (
    """CREATE TABLE target_state (
        target_id TEXT PRIMARY KEY,
        executable INTEGER NOT NULL CHECK (executable IN (0, 1)),
        skip_reason TEXT,
        outcome TEXT NOT NULL CHECK (outcome IN
            ('pending', 'skipped', 'acquired', 'not_filed', 'required_missing', 'ambiguous', 'failed')),
        source TEXT CHECK (source IS NULL OR source IN ('live_sec', 'fixture_replay')),
        retryable INTEGER NOT NULL DEFAULT 0 CHECK (retryable IN (0, 1)),
        attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
        last_attempt_id TEXT,
        error_code TEXT,
        source_sha256 TEXT,
        source_byte_size INTEGER CHECK (source_byte_size IS NULL OR source_byte_size >= 0),
        source_body_relative_path TEXT,
        selected_sha256 TEXT,
        selected_byte_size INTEGER CHECK (selected_byte_size IS NULL OR selected_byte_size >= 0),
        selected_body_relative_path TEXT,
        CHECK ((executable = 1 AND skip_reason IS NULL) OR
               (executable = 0 AND skip_reason IS NOT NULL)),
        CHECK ((outcome = 'skipped' AND executable = 0) OR
               (outcome <> 'skipped' AND executable = 1)),
        CHECK (outcome = 'failed' OR retryable = 0)
    )""",
    """CREATE TABLE attempts (
        attempt_id TEXT PRIMARY KEY,
        target_id TEXT NOT NULL REFERENCES target_state(target_id),
        attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
        outcome TEXT NOT NULL CHECK (outcome IN
            ('acquired', 'not_filed', 'required_missing', 'ambiguous', 'failed')),
        attempt_kind TEXT NOT NULL CHECK (attempt_kind IN ('document_body', 'lazy_index')),
        source TEXT NOT NULL CHECK (source IN ('live_sec', 'fixture_replay')),
        retryable INTEGER NOT NULL CHECK (retryable IN (0, 1)),
        error_code TEXT,
        http_status INTEGER,
        requested_url TEXT NOT NULL,
        final_url TEXT,
        started_at_utc TEXT NOT NULL,
        finished_at_utc TEXT NOT NULL,
        source_sha256 TEXT,
        source_byte_size INTEGER CHECK (source_byte_size IS NULL OR source_byte_size >= 0),
        source_body_relative_path TEXT,
        selected_sha256 TEXT,
        selected_byte_size INTEGER CHECK (selected_byte_size IS NULL OR selected_byte_size >= 0),
        selected_body_relative_path TEXT,
        UNIQUE (target_id, attempt_number),
        CHECK (outcome = 'failed' OR retryable = 0)
    )""",
    """CREATE TABLE target_slot_resolutions (
        resolution_id TEXT PRIMARY KEY,
        resolution_schema_version TEXT NOT NULL,
        target_id TEXT NOT NULL REFERENCES target_state(target_id),
        selector TEXT NOT NULL CHECK (selector IN ('submitted_primary', 'exact_form_with_lazy_index')),
        expected_statutory_type TEXT NOT NULL,
        initial_sequence INTEGER NOT NULL CHECK (initial_sequence = 1),
        screen_kind TEXT NOT NULL CHECK (screen_kind IN ('none', 'sgml_type', 'html_cover')),
        screen_result TEXT NOT NULL CHECK (screen_result IN ('not_run', 'form_match', 'type_mismatch', 'unverifiable')),
        evaluator_version TEXT,
        initial_body_sha256 TEXT NOT NULL,
        index_attempt_id TEXT REFERENCES attempts(attempt_id),
        index_response_sha256 TEXT,
        index_parser_version TEXT,
        matching_entry_ids_json TEXT NOT NULL,
        selected_sequence INTEGER CHECK (selected_sequence IS NULL OR selected_sequence > 0),
        selected_retrieval_mode TEXT CHECK (selected_retrieval_mode IS NULL OR selected_retrieval_mode IN ('direct_url', 'bundle_sequence')),
        selected_url TEXT,
        result TEXT NOT NULL CHECK (result IN ('accepted_sequence_1', 'recovered', 'not_filed', 'required_missing', 'ambiguous', 'failed')),
        recorded_at_utc TEXT NOT NULL
    )""",
    "CREATE INDEX attempts_target_number ON attempts(target_id, attempt_number)",
    "CREATE INDEX target_state_retry ON target_state(outcome, retryable, executable)",
    """CREATE TRIGGER attempts_no_update BEFORE UPDATE ON attempts
       BEGIN SELECT RAISE(ABORT, 'attempt records are append-only'); END""",
    """CREATE TRIGGER attempts_no_delete BEFORE DELETE ON attempts
       BEGIN SELECT RAISE(ABORT, 'attempt records are append-only'); END""",
    """CREATE TRIGGER resolutions_no_update BEFORE UPDATE ON target_slot_resolutions
       BEGIN SELECT RAISE(ABORT, 'resolution records are append-only'); END""",
    """CREATE TRIGGER resolutions_no_delete BEFORE DELETE ON target_slot_resolutions
       BEGIN SELECT RAISE(ABORT, 'resolution records are append-only'); END""",
)
_INSERT_TARGET = """INSERT INTO target_state
    (target_id, executable, skip_reason, outcome)
    VALUES (?, ?, ?, ?)"""
_INSERT_ATTEMPT = """INSERT INTO attempts (
    attempt_id, target_id, attempt_number, outcome, attempt_kind, source, retryable,
    error_code, http_status, requested_url, final_url, started_at_utc,
    finished_at_utc, source_sha256, source_byte_size, source_body_relative_path,
    selected_sha256, selected_byte_size, selected_body_relative_path
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
_UPDATE_TARGET = """UPDATE target_state SET
    outcome = ?, source = ?, retryable = ?, attempt_count = ?, last_attempt_id = ?,
    error_code = ?, source_sha256 = ?, source_byte_size = ?,
    source_body_relative_path = ?, selected_sha256 = ?, selected_byte_size = ?,
    selected_body_relative_path = ?
WHERE target_id = ? AND executable = 1"""
_INSERT_RESOLUTION = """INSERT INTO target_slot_resolutions (
    resolution_id, resolution_schema_version, target_id, selector,
    expected_statutory_type, initial_sequence, screen_kind, screen_result,
    evaluator_version, initial_body_sha256, index_attempt_id,
    index_response_sha256, index_parser_version, matching_entry_ids_json,
    selected_sequence, selected_retrieval_mode, selected_url, result, recorded_at_utc
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
_SELECT_PENDING = """SELECT target_id, executable, skip_reason, outcome, source, retryable,
    attempt_count, last_attempt_id, error_code, source_sha256, source_byte_size,
    source_body_relative_path, selected_sha256, selected_byte_size,
    selected_body_relative_path
FROM target_state WHERE outcome = 'pending' ORDER BY target_id"""
_SELECT_RETRY = """SELECT target_id, executable, skip_reason, outcome, source, retryable,
    attempt_count, last_attempt_id, error_code, source_sha256, source_byte_size,
    source_body_relative_path, selected_sha256, selected_byte_size,
    selected_body_relative_path
FROM target_state
WHERE outcome = 'pending' OR (outcome = 'failed' AND retryable = 1)
ORDER BY target_id"""
_COUNT_OUTCOMES = (
    "SELECT outcome, COUNT(*) FROM target_state GROUP BY outcome ORDER BY outcome"
)
_COUNT_RETRYABLE = """SELECT COUNT(*) FROM target_state
WHERE outcome = ? AND retryable = ?"""
_GET_TARGET = """SELECT target_id, executable, skip_reason, outcome, source, retryable,
    attempt_count, last_attempt_id, error_code, source_sha256, source_byte_size,
    source_body_relative_path, selected_sha256, selected_byte_size,
    selected_body_relative_path
FROM target_state WHERE target_id = ?"""
_GET_ATTEMPT = """SELECT attempt_id, target_id, attempt_number, attempt_kind, source,
    requested_url, outcome, retryable, error_code, http_status, final_url,
    started_at_utc, finished_at_utc, source_sha256, source_byte_size,
    source_body_relative_path, selected_sha256, selected_byte_size,
    selected_body_relative_path
FROM attempts WHERE target_id = ? AND attempt_id = ?"""
_COUNT_ATTEMPTED = "SELECT COUNT(*) FROM target_state WHERE attempt_count > 0"


class RunStateError(RuntimeError):
    pass


def _connect(database_path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        uri = f"file:{quote(str(database_path.resolve()), safe='/')}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, isolation_level=None)
    else:
        connection = sqlite3.connect(database_path, isolation_level=None)
    connection.execute("PRAGMA foreign_keys = ON")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        connection.close()
        raise RunStateError("SQLite foreign-key enforcement is unavailable")
    return connection


def _require_schema(connection: sqlite3.Connection) -> None:
    if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
        raise RunStateError("unsupported run-state schema version")


def _field(target: object, name: str) -> object:
    if isinstance(target, Mapping):
        return target[name]
    return getattr(target, name)


def _target_seed(target: object) -> tuple[str, int, str | None, str]:
    target_id = _field(target, "target_id")
    executable = _field(target, "executable")
    skip_reason = _field(target, "skip_reason")
    if not isinstance(target_id, str) or not target_id:
        raise ValueError("work-order target ID must be a non-empty string")
    if not isinstance(executable, bool):
        raise ValueError("work-order executable flag must be boolean")
    if executable and skip_reason is not None:
        raise ValueError("executable work-order targets cannot have a skip reason")
    if not executable and (not isinstance(skip_reason, str) or not skip_reason):
        raise ValueError("skipped work-order targets require a skip reason")
    return (
        target_id,
        int(executable),
        skip_reason,
        "pending" if executable else "skipped",
    )


def initialize_run_state(
    database_path: Path,
    targets: Iterable[WorkOrderTargetSeed | Mapping[str, object]],
) -> None:
    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = _connect(database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        tables = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
        if version == 0 and tables == 0:
            for statement in _SCHEMA:
                connection.execute(statement)
            connection.execute(
                f"PRAGMA user_version = {sql_literal(str(SCHEMA_VERSION))}"
            )
        elif version != SCHEMA_VERSION:
            raise RunStateError("unsupported run-state schema version")
        for target in targets:
            connection.execute(_INSERT_TARGET, _target_seed(target))
        connection.execute("COMMIT")
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def _url_value(value: str | None, name: str, *, required: bool) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be a non-empty exact URL")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError as error:
        raise ValueError(f"{name} is malformed") from error
    if (
        parts.scheme != "https"
        or parts.hostname != "www.sec.gov"
        or parts.username is not None
        or parts.password is not None
        or port is not None
        or "?" in value
        or "#" in value
    ):
        raise ValueError(f"{name} must omit credentials, query, and fragment")
    return value


def _attempt_values(attempt: AcquisitionAttempt) -> tuple[object, ...]:
    requested_url = _url_value(attempt.requested_url, "requested_url", required=True)
    final_url = _url_value(attempt.final_url, "final_url", required=False)
    if not isinstance(attempt.retryable, bool):
        raise ValueError("attempt retryable flag must be boolean")
    return (
        attempt.attempt_id,
        attempt.target_id,
        attempt.attempt_number,
        attempt.outcome,
        attempt.attempt_kind,
        attempt.source,
        int(attempt.retryable),
        attempt.error_code,
        attempt.http_status,
        requested_url,
        final_url,
        attempt.started_at_utc,
        attempt.finished_at_utc,
        attempt.source_sha256,
        attempt.source_byte_size,
        attempt.source_body_relative_path,
        attempt.selected_sha256,
        attempt.selected_byte_size,
        attempt.selected_body_relative_path,
    )


def append_attempt_and_update_target(
    database_path: Path,
    attempt: AcquisitionAttempt,
    outcome: AcquisitionOutcome,
) -> None:
    values = _attempt_values(attempt)
    if attempt.target_id != outcome.target_id:
        raise ValueError("attempt and outcome target IDs differ")
    if attempt.outcome != outcome.status:
        raise ValueError("attempt and target outcome differ")
    if attempt.source != outcome.source or attempt.retryable != outcome.retryable:
        raise ValueError("attempt and target source/retry state differ")
    if (
        attempt.error_code != outcome.error_code
        or attempt.source_sha256 != outcome.source_sha256
        or attempt.source_byte_size != outcome.source_byte_size
        or attempt.source_body_relative_path != outcome.source_body_relative_path
        or attempt.selected_sha256 != outcome.selected_sha256
        or attempt.selected_byte_size != outcome.selected_byte_size
        or attempt.selected_body_relative_path != outcome.selected_body_relative_path
    ):
        raise ValueError("attempt and target evidence differ")
    connection = _connect(Path(database_path))
    try:
        _require_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        current = connection.execute(
            "SELECT executable, attempt_count, outcome, retryable FROM target_state "
            "WHERE target_id = ?",
            (attempt.target_id,),
        ).fetchone()
        if current is None or current[0] != 1:
            raise RunStateError("attempt target is missing or not executable")
        if attempt.attempt_number != current[1] + 1:
            raise RunStateError("attempt number is not the next target attempt")
        if current[2] != "pending" and not (current[2] == "failed" and current[3] == 1):
            raise RunStateError("target outcome is not eligible for an attempt")
        if (
            outcome.attempt_count != attempt.attempt_number
            or outcome.last_attempt_id != attempt.attempt_id
        ):
            raise ValueError("outcome attempt projection is inconsistent")
        connection.execute(_INSERT_ATTEMPT, values)
        cursor = connection.execute(
            _UPDATE_TARGET,
            (
                outcome.status,
                outcome.source,
                int(outcome.retryable),
                outcome.attempt_count,
                outcome.last_attempt_id,
                outcome.error_code,
                outcome.source_sha256,
                outcome.source_byte_size,
                outcome.source_body_relative_path,
                outcome.selected_sha256,
                outcome.selected_byte_size,
                outcome.selected_body_relative_path,
                outcome.target_id,
            ),
        )
        if cursor.rowcount != 1:
            raise RunStateError("target projection update did not match one target")
        connection.execute("COMMIT")
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def commit_attempts_and_update_target(
    database_path: Path,
    attempts: Iterable[AcquisitionAttempt],
    outcome: AcquisitionOutcome,
    *,
    resolution: TargetSlotResolution | None = None,
    recorded_at_utc: str | None = None,
) -> None:
    attempts = tuple(attempts)
    if not attempts:
        raise ValueError("at least one acquisition attempt is required")
    if any(attempt.target_id != outcome.target_id for attempt in attempts):
        raise ValueError("attempts and outcome target IDs differ")
    values = tuple(_attempt_values(attempt) for attempt in attempts)
    if resolution is not None:
        if resolution.target_id != outcome.target_id:
            raise ValueError("resolution and outcome target IDs differ")
        if resolution.index_attempt_id is None:
            raise ValueError("resolution must reference its lazy-index attempt")
        if not recorded_at_utc:
            raise ValueError("recorded_at_utc is required with a resolution")
        expected_status = {
            "accepted_sequence_1": "acquired",
            "recovered": "acquired",
            "not_filed": "not_filed",
            "required_missing": "required_missing",
            "ambiguous": "ambiguous",
            "failed": "failed",
        }[resolution.result]
        if outcome.status != expected_status:
            raise ValueError("resolution result and target outcome differ")

    connection = _connect(Path(database_path))
    try:
        _require_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        current = connection.execute(
            "SELECT executable, attempt_count, outcome, retryable FROM target_state "
            "WHERE target_id = ?",
            (outcome.target_id,),
        ).fetchone()
        if current is None or current[0] != 1:
            raise RunStateError("attempt target is missing or not executable")
        if current[2] != "pending" and not (current[2] == "failed" and current[3] == 1):
            raise RunStateError("target outcome is not eligible for an attempt")
        first_number = current[1] + 1
        if tuple(attempt.attempt_number for attempt in attempts) != tuple(
            range(first_number, first_number + len(attempts))
        ):
            raise RunStateError("attempt numbers are not contiguous for the target")
        final_attempt = attempts[-1]
        if (
            outcome.attempt_count != final_attempt.attempt_number
            or outcome.last_attempt_id != final_attempt.attempt_id
        ):
            raise ValueError("outcome attempt projection is inconsistent")
        if outcome.source != final_attempt.source or (
            outcome.retryable != final_attempt.retryable
        ):
            raise ValueError("outcome source/retry state differs from final attempt")
        for attempt_values in values:
            connection.execute(_INSERT_ATTEMPT, attempt_values)
        if resolution is not None and resolution.index_attempt_id is not None:
            index_attempt = connection.execute(
                "SELECT target_id, attempt_kind FROM attempts WHERE attempt_id = ?",
                (resolution.index_attempt_id,),
            ).fetchone()
            if index_attempt != (outcome.target_id, "lazy_index"):
                raise ValueError("resolution index attempt is missing or mismatched")
            selected_url = _url_value(
                resolution.selected_url, "selected_url", required=False
            )
            connection.execute(
                _INSERT_RESOLUTION,
                (
                    resolution.resolution_id,
                    resolution.resolution_schema_version,
                    resolution.target_id,
                    resolution.selector,
                    resolution.expected_statutory_type,
                    resolution.initial_sequence,
                    resolution.screen_kind,
                    resolution.screen_result,
                    resolution.evaluator_version,
                    resolution.initial_body_sha256,
                    resolution.index_attempt_id,
                    resolution.index_response_sha256,
                    resolution.index_parser_version,
                    json.dumps(
                        list(resolution.matching_entry_ids),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    resolution.selected_sequence,
                    resolution.selected_retrieval_mode,
                    selected_url,
                    resolution.result,
                    recorded_at_utc,
                ),
            )
        cursor = connection.execute(
            _UPDATE_TARGET,
            (
                outcome.status,
                outcome.source,
                int(outcome.retryable),
                outcome.attempt_count,
                outcome.last_attempt_id,
                outcome.error_code,
                outcome.source_sha256,
                outcome.source_byte_size,
                outcome.source_body_relative_path,
                outcome.selected_sha256,
                outcome.selected_byte_size,
                outcome.selected_body_relative_path,
                outcome.target_id,
            ),
        )
        if cursor.rowcount != 1:
            raise RunStateError("target projection update did not match one target")
        connection.execute("COMMIT")
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def append_target_slot_resolution(
    database_path: Path,
    resolution: TargetSlotResolution,
    *,
    recorded_at_utc: str,
) -> None:
    if not recorded_at_utc:
        raise ValueError("recorded_at_utc is required")
    selected_url = _url_value(resolution.selected_url, "selected_url", required=False)
    matching_ids = json.dumps(
        list(resolution.matching_entry_ids), ensure_ascii=False, separators=(",", ":")
    )
    values = (
        resolution.resolution_id,
        resolution.resolution_schema_version,
        resolution.target_id,
        resolution.selector,
        resolution.expected_statutory_type,
        resolution.initial_sequence,
        resolution.screen_kind,
        resolution.screen_result,
        resolution.evaluator_version,
        resolution.initial_body_sha256,
        resolution.index_attempt_id,
        resolution.index_response_sha256,
        resolution.index_parser_version,
        matching_ids,
        resolution.selected_sequence,
        resolution.selected_retrieval_mode,
        selected_url,
        resolution.result,
        recorded_at_utc,
    )
    connection = _connect(Path(database_path))
    try:
        _require_schema(connection)
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(_INSERT_RESOLUTION, values)
        connection.execute("COMMIT")
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


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


def get_target_states(
    database_path: Path, target_ids: Iterable[str]
) -> dict[str, TargetState]:
    target_ids = tuple(target_ids)
    if not target_ids:
        return {}
    connection = _connect(Path(database_path), readonly=True)
    try:
        _require_schema(connection)
        result = {}
        for target_id in target_ids:
            row = connection.execute(_GET_TARGET, (target_id,)).fetchone()
            if row is not None:
                result[target_id] = _target_state_from_row(row)
        return result
    finally:
        connection.close()


def _validate_readonly(connection: sqlite3.Connection) -> None:
    integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    foreign_key_error = connection.execute("PRAGMA foreign_key_check").fetchone()
    if integrity != "ok" or foreign_key_error is not None:
        raise RunStateError(
            f"integrity_check={integrity!r}; foreign_key_check={foreign_key_error!r}"
        )


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
    "SCHEMA_VERSION",
    "RunStateError",
    "append_attempt_and_update_target",
    "append_target_slot_resolution",
    "commit_attempts_and_update_target",
    "get_attempt",
    "get_target_state",
    "get_target_states",
    "inspect_run_state",
    "initialize_run_state",
    "iter_selected_target_states",
    "summarize_target_state",
    "validate_run_state",
]
