from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.pipelines.document_acquisition.models import OperationAttempt
from edgar_sec.pipelines.document_acquisition.run_state.models import (
    OperationState,
    WorkOrderOperationSeed,
    _operation_attempt_from_row,
    _operation_state_from_row,
)

_SCHEMA = (
    """CREATE TABLE operation_state (
        operation_id TEXT PRIMARY KEY,
        target_id TEXT NOT NULL REFERENCES target_state(target_id),
        operation TEXT NOT NULL,
        requested INTEGER NOT NULL CHECK (requested IN (0, 1)),
        request_mode TEXT NOT NULL CHECK (request_mode IN
            ('mandatory_raw', 'profile', 'default_candidate', 'not_requested')),
        selected INTEGER NOT NULL CHECK (selected IN (0, 1)),
        source_request_id TEXT,
        input_ordinal INTEGER CHECK (input_ordinal IS NULL OR input_ordinal = 0),
        input_role TEXT,
        support_status TEXT NOT NULL CHECK (support_status IN
            ('supported', 'unsupported', 'not_evaluated')),
        support_reason TEXT,
        capability_id TEXT,
        capability_version TEXT,
        handler_id TEXT,
        handler_version TEXT,
        output_kind TEXT,
        status TEXT NOT NULL CHECK (status IN
            ('pending', 'not_requested', 'unsupported', 'not_selected', 'blocked', 'succeeded', 'failed')),
        retryable INTEGER NOT NULL DEFAULT 0 CHECK (retryable IN (0, 1)),
        attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
        last_attempt_id TEXT,
        error_code TEXT,
        CHECK ((requested = 0 AND request_mode = 'not_requested' AND
                selected = 0 AND support_status = 'not_evaluated' AND
                status = 'not_requested') OR
               (requested = 1 AND request_mode = 'default_candidate' AND
                selected = 0 AND support_status IN ('supported', 'unsupported') AND
                status = 'not_selected') OR
               (requested = 1 AND request_mode <> 'default_candidate' AND
                support_status = 'unsupported' AND selected = 0 AND
                status = 'unsupported') OR
               (requested = 1 AND request_mode <> 'default_candidate' AND
                support_status = 'supported' AND selected = 0 AND
                status = 'not_selected') OR
               (requested = 1 AND request_mode <> 'not_requested' AND
                support_status = 'supported' AND selected = 1 AND
                status IN ('pending', 'blocked', 'succeeded', 'failed'))),
        CHECK ((source_request_id IS NULL AND input_ordinal IS NULL AND input_role IS NULL) OR
               (source_request_id IS NOT NULL AND input_ordinal = 0 AND
                input_role = 'selected_target_body')),
        CHECK ((support_status = 'supported' AND support_reason IS NULL AND
                capability_id IS NOT NULL AND capability_version IS NOT NULL AND
                handler_id IS NOT NULL AND handler_version IS NOT NULL AND
                output_kind IS NOT NULL) OR
               (support_status = 'unsupported' AND support_reason IS NOT NULL AND
                capability_id IS NULL AND capability_version IS NULL AND
                handler_id IS NULL AND handler_version IS NULL AND output_kind IS NULL) OR
               (support_status = 'not_evaluated' AND support_reason IS NULL AND
                capability_id IS NULL AND capability_version IS NULL AND
                handler_id IS NULL AND handler_version IS NULL AND output_kind IS NULL)),
        CHECK (selected = 0 OR support_status = 'supported'),
        CHECK (status IN ('blocked', 'unsupported', 'failed') OR error_code IS NULL),
        CHECK (status = 'failed' OR retryable = 0)
    )""",
    """CREATE TABLE operation_attempts (
        attempt_id TEXT PRIMARY KEY,
        operation_id TEXT NOT NULL REFERENCES operation_state(operation_id),
        attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
        outcome TEXT NOT NULL CHECK (outcome IN ('succeeded', 'failed')),
        retryable INTEGER NOT NULL CHECK (retryable IN (0, 1)),
        error_code TEXT,
        started_at_utc TEXT NOT NULL,
        finished_at_utc TEXT NOT NULL,
        UNIQUE (operation_id, attempt_number),
        CHECK (outcome = 'failed' OR retryable = 0)
    )""",
    "CREATE INDEX operation_state_retry ON operation_state(status, retryable, requested)",
    """CREATE TRIGGER operation_attempts_no_update BEFORE UPDATE ON operation_attempts
       BEGIN SELECT RAISE(ABORT, 'operation attempt records are append-only'); END""",
    """CREATE TRIGGER operation_attempts_no_delete BEFORE DELETE ON operation_attempts
       BEGIN SELECT RAISE(ABORT, 'operation attempt records are append-only'); END""",
)


def create_operation_schema(connection: sqlite3.Connection) -> None:
    for statement in _SCHEMA:
        connection.execute(statement)


def _field(operation: object, name: str) -> object:
    if isinstance(operation, dict):
        return operation[name]
    return getattr(operation, name)


def _operation_seed(operation: object) -> tuple[object, ...]:
    values = tuple(
        _field(operation, name)
        for name in (
            "operation_id",
            "target_id",
            "operation",
            "requested",
            "request_mode",
            "selected",
            "source_request_id",
            "input_ordinal",
            "input_role",
            "support_status",
            "support_reason",
            "capability_id",
            "capability_version",
            "handler_id",
            "handler_version",
            "output_kind",
        )
    )
    (
        operation_id,
        target_id,
        name,
        requested,
        request_mode,
        selected,
        source_request_id,
        input_ordinal,
        input_role,
        support_status,
        support_reason,
        capability_id,
        capability_version,
        handler_id,
        handler_version,
        output_kind,
    ) = values
    if not all(
        isinstance(value, str) and value for value in (operation_id, target_id, name)
    ):
        raise ValueError("work-order operation identity must be non-empty")
    if name not in {
        "raw",
        "render_to_txt",
        "render_to_xml",
    } or operation_id != canonical_hash([target_id, name]):
        raise ValueError("work-order operation ID does not match its identity")
    if type(requested) is not bool or type(selected) is not bool:
        raise ValueError("work-order operation flags must be boolean")
    if request_mode not in {
        "mandatory_raw",
        "profile",
        "default_candidate",
        "not_requested",
    }:
        raise ValueError("work-order operation request mode is invalid")
    if name == "raw" and (not requested or request_mode != "mandatory_raw"):
        raise ValueError("raw operation intent is not mandatory")
    if name != "raw" and (
        (requested and request_mode not in {"profile", "default_candidate"})
        or (not requested and request_mode != "not_requested")
    ):
        raise ValueError("operation request mode disagrees with requested flag")
    if support_status not in {"supported", "unsupported", "not_evaluated"}:
        raise ValueError("resolved operation support status is invalid")
    pins = (capability_id, capability_version, handler_id, handler_version, output_kind)
    if support_status == "supported" and (
        any(not isinstance(value, str) or not value for value in pins)
        or support_reason is not None
    ):
        raise ValueError("supported operation does not contain complete pins")
    if support_status == "unsupported" and (
        any(value is not None for value in pins)
        or not isinstance(support_reason, str)
        or not support_reason
    ):
        raise ValueError("unsupported operation does not contain a reason")
    if support_status == "not_evaluated" and (
        requested
        or any(value is not None for value in pins)
        or support_reason is not None
    ):
        raise ValueError("unevaluated operation has resolved pins")
    if selected and (not requested or support_status != "supported"):
        raise ValueError("unrequested or unsupported operation was selected")
    if (source_request_id is None) != (input_ordinal is None) or (
        source_request_id is None
    ) != (input_role is None):
        raise ValueError("resolved operation input references are incomplete")
    if input_ordinal is not None and (
        input_ordinal != 0 or input_role != "selected_target_body"
    ):
        raise ValueError("resolved operation input reference is invalid")
    status = (
        "not_requested"
        if not requested
        else "not_selected"
        if request_mode == "default_candidate" and not selected
        else "unsupported"
        if support_status == "unsupported"
        else "not_selected"
        if not selected
        else "blocked"
    )
    error_code = (
        f"unsupported:{support_reason}"
        if status == "unsupported"
        else "blocked:acquisition_not_ready"
        if status == "blocked"
        else None
    )
    return (*values, status, 0, 0, None, error_code)


def seed_operation_state(
    connection: sqlite3.Connection,
    operations: object,
) -> None:
    connection.executemany(
        """INSERT INTO operation_state (
            operation_id, target_id, operation, requested, request_mode, selected,
            source_request_id, input_ordinal, input_role, support_status, support_reason,
            capability_id, capability_version, handler_id, handler_version, output_kind,
            status, retryable, attempt_count, last_attempt_id, error_code
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (_operation_seed(operation) for operation in operations),
    )


def operation_attempt_id(operation_id: str, attempt_number: int) -> str:
    if (
        not isinstance(operation_id, str)
        or not operation_id
        or isinstance(attempt_number, bool)
        or not isinstance(attempt_number, int)
        or attempt_number < 1
    ):
        raise ValueError("operation attempt identity is invalid")
    return canonical_hash([operation_id, attempt_number])


def _connect(database_path: Path, *, readonly: bool) -> sqlite3.Connection:
    if readonly:
        uri = f"file:{quote(str(database_path.resolve()), safe='/')}?mode=ro"
        connection = sqlite3.connect(uri, uri=True, isolation_level=None)
    else:
        connection = sqlite3.connect(database_path, isolation_level=None)
    connection.execute("PRAGMA foreign_keys = ON")
    if connection.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        connection.close()
        raise RuntimeError("SQLite foreign-key enforcement is unavailable")
    from edgar_sec.pipelines.document_acquisition.run_state.store import SCHEMA_VERSION

    if connection.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
        connection.close()
        raise RuntimeError("unsupported run-state schema version")
    return connection


def append_operation_attempt(database_path: Path, attempt: OperationAttempt) -> None:
    if (
        not isinstance(attempt.attempt_number, int)
        or isinstance(attempt.attempt_number, bool)
        or attempt.attempt_number < 1
        or attempt.attempt_id
        != operation_attempt_id(attempt.operation_id, attempt.attempt_number)
        or not attempt.started_at_utc
        or not attempt.finished_at_utc
        or type(attempt.retryable) is not bool
        or attempt.outcome not in {"succeeded", "failed"}
        or (attempt.outcome == "succeeded" and attempt.retryable)
    ):
        raise ValueError("operation attempt identity or fields are invalid")
    connection = _connect(Path(database_path), readonly=False)
    try:
        connection.execute("BEGIN IMMEDIATE")
        current = connection.execute(
            "SELECT requested, selected, support_status, status, retryable, attempt_count "
            "FROM operation_state WHERE operation_id = ?",
            (attempt.operation_id,),
        ).fetchone()
        if (
            current is None
            or current[0] != 1
            or current[1] != 1
            or current[2] != "supported"
        ):
            from edgar_sec.pipelines.document_acquisition.run_state.store import (
                RunStateError,
            )

            raise RunStateError("operation is missing or unrequested")
        if attempt.attempt_number != current[5] + 1:
            from edgar_sec.pipelines.document_acquisition.run_state.store import (
                RunStateError,
            )

            raise RunStateError("operation attempt number is not the next attempt")
        if current[3] != "pending" and not (current[3] == "failed" and current[4] == 1):
            from edgar_sec.pipelines.document_acquisition.run_state.store import (
                RunStateError,
            )

            raise RunStateError("operation status is not eligible for an attempt")
        connection.execute(
            "INSERT INTO operation_attempts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                attempt.attempt_id,
                attempt.operation_id,
                attempt.attempt_number,
                attempt.outcome,
                int(attempt.retryable),
                attempt.error_code,
                attempt.started_at_utc,
                attempt.finished_at_utc,
            ),
        )
        connection.execute(
            "UPDATE operation_state SET status = ?, retryable = ?, "
            "attempt_count = ?, last_attempt_id = ?, error_code = ? "
            "WHERE operation_id = ?",
            (
                "succeeded" if attempt.outcome == "succeeded" else "failed",
                int(attempt.retryable),
                attempt.attempt_number,
                attempt.attempt_id,
                attempt.error_code,
                attempt.operation_id,
            ),
        )
        connection.execute("COMMIT")
    except Exception:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
    finally:
        connection.close()


def refresh_operation_readiness(connection: sqlite3.Connection, target_id: str) -> int:
    rows = connection.execute(
        """SELECT operation.operation_id, target.outcome,
            target.selected_body_relative_path
        FROM operation_state operation JOIN target_state target USING (target_id)
        WHERE operation.target_id = ? AND operation.requested = 1
            AND operation.selected = 1 AND operation.support_status = 'supported'
            AND operation.attempt_count = 0""",
        (target_id,),
    ).fetchall()
    changed = 0
    for operation_id, outcome, selected_path in rows:
        ready = outcome == "acquired" and selected_path is not None
        status = "pending" if ready else "blocked"
        error_code = None if ready else "blocked:acquisition_not_ready"
        cursor = connection.execute(
            "UPDATE operation_state SET status = ?, retryable = 0, error_code = ? "
            "WHERE operation_id = ? AND status IN ('pending', 'blocked')",
            (status, error_code, operation_id),
        )
        changed += cursor.rowcount
    return changed


def get_operation_state(
    database_path: Path, operation_id: str
) -> OperationState | None:
    connection = _connect(Path(database_path), readonly=True)
    try:
        row = connection.execute(
            """SELECT operation_id, target_id, operation, requested,
                request_mode, selected, source_request_id, input_ordinal,
                input_role, support_status, support_reason, capability_id,
                capability_version, handler_id, handler_version, output_kind,
                status, retryable, attempt_count, last_attempt_id, error_code
            FROM operation_state WHERE operation_id = ?""",
            (operation_id,),
        ).fetchone()
        return None if row is None else _operation_state_from_row(row)
    finally:
        connection.close()


def list_operation_attempts(
    database_path: Path, operation_id: str
) -> tuple[OperationAttempt, ...]:
    connection = _connect(Path(database_path), readonly=True)
    try:
        return tuple(
            _operation_attempt_from_row(row)
            for row in connection.execute(
                """SELECT attempt_id, operation_id, attempt_number, outcome,
                    retryable, error_code, started_at_utc, finished_at_utc
                FROM operation_attempts WHERE operation_id = ?
                ORDER BY attempt_number""",
                (operation_id,),
            )
        )
    finally:
        connection.close()


def iter_operation_states(
    database_path: Path, target_id: str | None = None
) -> Iterator[OperationState]:
    connection = _connect(Path(database_path), readonly=True)
    try:
        query = """SELECT operation_id, target_id, operation, requested,
            request_mode, selected, source_request_id, input_ordinal,
            input_role, support_status, support_reason, capability_id,
            capability_version, handler_id, handler_version, output_kind,
            status, retryable, attempt_count, last_attempt_id, error_code
        FROM operation_state"""
        parameters: tuple[str, ...] = ()
        if target_id is not None:
            query += " WHERE target_id = ?"
            parameters = (target_id,)
        query += " ORDER BY target_id, operation"
        for row in connection.execute(query, parameters):
            yield _operation_state_from_row(row)
    finally:
        connection.close()


def validate_operation_state(connection: sqlite3.Connection) -> None:
    from edgar_sec.pipelines.document_acquisition.run_state.store import RunStateError

    mismatch = connection.execute(
        """SELECT count(*) FROM operation_state state
        LEFT JOIN (
            SELECT operation_id, count(*) AS attempts, min(attempt_number) AS first,
                max(attempt_number) AS last
            FROM operation_attempts GROUP BY operation_id
        ) history USING (operation_id)
        LEFT JOIN operation_attempts latest
            ON latest.operation_id = state.operation_id
            AND latest.attempt_number = state.attempt_count
            JOIN target_state target USING (target_id)
            WHERE state.attempt_count <> coalesce(history.attempts, 0)
            OR (state.attempt_count = 0 AND (
                state.last_attempt_id IS NOT NULL OR state.retryable <> 0
                OR state.status <> CASE
                    WHEN state.requested = 0 THEN 'not_requested'
                    WHEN state.request_mode = 'default_candidate'
                        AND state.selected = 0 THEN 'not_selected'
                    WHEN state.support_status = 'unsupported' THEN 'unsupported'
                    WHEN state.selected = 0 THEN 'not_selected'
                    WHEN target.outcome = 'acquired'
                        AND target.selected_body_relative_path IS NOT NULL THEN 'pending'
                    ELSE 'blocked' END
                OR state.error_code IS NOT CASE
                    WHEN state.status = 'blocked' THEN 'blocked:acquisition_not_ready'
                    WHEN state.status = 'unsupported' THEN
                        'unsupported:' || state.support_reason
                    ELSE NULL END))
            OR (state.attempt_count > 0 AND (
                history.first <> 1 OR history.last <> state.attempt_count
                OR state.requested <> 1 OR state.selected <> 1
                OR state.support_status <> 'supported'
                OR latest.attempt_id IS NOT state.last_attempt_id
                OR latest.error_code IS NOT state.error_code
                OR latest.retryable <> state.retryable
                OR latest.outcome <> state.status))"""
    ).fetchone()[0]
    if mismatch:
        raise RunStateError("operation state does not match its attempt history")
    for operation_id, target_id, operation in connection.execute(
        "SELECT operation_id, target_id, operation FROM operation_state"
    ):
        if operation_id != canonical_hash([target_id, operation]):
            raise RunStateError("operation state identity is invalid")


__all__ = [
    "append_operation_attempt",
    "create_operation_schema",
    "get_operation_state",
    "iter_operation_states",
    "list_operation_attempts",
    "operation_attempt_id",
    "refresh_operation_readiness",
    "seed_operation_state",
    "validate_operation_state",
]
