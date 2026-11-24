from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from urllib.parse import urlsplit

from edgar_sec.infra.storage.duckdb import sql_literal
from edgar_sec.pipelines.document_acquisition.models import (
    AcquisitionAttempt,
    AcquisitionOutcome,
    TargetSlotResolution,
)
from edgar_sec.pipelines.document_acquisition.run_state.models import (
    WorkOrderOperationSeed,
    WorkOrderTargetSeed,
)
from edgar_sec.pipelines.document_acquisition.run_state.operations import (
    create_operation_schema,
    refresh_operation_readiness,
    seed_operation_state,
)
from edgar_sec.pipelines.document_acquisition.run_state.schema import (
    SCHEMA_VERSION,
    _INSERT_ATTEMPT,
    _INSERT_RESOLUTION,
    _INSERT_TARGET,
    _SCHEMA,
    _UPDATE_TARGET,
)
from edgar_sec.pipelines.document_acquisition.run_state.store import (
    RunStateError,
    _connect,
    _require_schema,
)


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
    operations: Iterable[WorkOrderOperationSeed | Mapping[str, object]] = (),
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
            create_operation_schema(connection)
            connection.execute(
                f"PRAGMA user_version = {sql_literal(str(SCHEMA_VERSION))}"
            )
        elif version != SCHEMA_VERSION:
            raise RunStateError("unsupported run-state schema version")
        for target in targets:
            connection.execute(_INSERT_TARGET, _target_seed(target))
        seed_operation_state(connection, operations)
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
        attempt.selected_filename,
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
        refresh_operation_readiness(connection, outcome.target_id)
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
        if resolution.selector == "sgml_bundle_scan":
            if resolution.index_attempt_id is not None:
                raise ValueError(
                    "bundle-scan resolution must not reference an index attempt"
                )
        elif resolution.index_attempt_id is None:
            raise ValueError("resolution must reference its lazy-index attempt")
        if not recorded_at_utc:
            raise ValueError("recorded_at_utc is required with a resolution")
        expected_status = {
            "accepted_sequence_1": "acquired",
            "recovered": "acquired",
            "selected_in_bundle": "acquired",
            "not_filed": "not_filed",
            "required_missing": "required_missing",
            "ambiguous": "ambiguous",
            "failed": "failed",
        }[resolution.result]
        if (
            outcome.status == "acquired"
            and resolution.selected_url is None
            and resolution.result
            in {"not_filed", "required_missing", "ambiguous", "failed"}
        ):
            expected_status = "acquired"
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
        if resolution is not None:
            if resolution.index_attempt_id is not None:
                index_attempt = connection.execute(
                    "SELECT target_id, attempt_kind FROM attempts WHERE attempt_id = ?",
                    (resolution.index_attempt_id,),
                ).fetchone()
                if index_attempt != (outcome.target_id, "lazy_index"):
                    raise ValueError(
                        "resolution index attempt is missing or mismatched"
                    )
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
        refresh_operation_readiness(connection, outcome.target_id)
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


__all__ = [
    "append_attempt_and_update_target",
    "append_target_slot_resolution",
    "commit_attempts_and_update_target",
    "initialize_run_state",
]
