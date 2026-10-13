"""Execute validated S9 work orders with bounded response staging."""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from edgar_sec.foundation.runtime.resources import derive_resources
from edgar_sec.pipelines.document_acquisition.models import (
    AcquisitionAttempt,
    AcquisitionOutcome,
    AcquisitionPolicy,
    AcquisitionRunReport,
    TargetSlotResolution,
)
from edgar_sec.pipelines.document_acquisition.paths import AcquisitionPaths
from edgar_sec.pipelines.document_acquisition.run_state.locks import RunLock
from edgar_sec.pipelines.document_acquisition.run_state.store import (
    commit_attempts_and_update_target,
    get_target_state,
    inspect_run_state,
    iter_target_state_pairs,
    summarize_target_state,
)
from edgar_sec.pipelines.document_acquisition.processing.run import (
    _read_relation_spool,
    _TERMINAL_OPERATION_STATUSES,
    _operation_status,
    process_acquired_target,
)
from edgar_sec.pipelines.document_acquisition.run_state.operations import (
    iter_operation_states,
)
from edgar_sec.pipelines.document_acquisition.run_validation import (
    iter_work_order_rows,
    load_validated_work_order,
)
from edgar_sec.pipelines.document_acquisition.target_runner import (
    AcquisitionTransport,
    acquire_target,
)


def _commit(
    paths: AcquisitionPaths,
    row: dict[str, object],
    attempts: tuple[AcquisitionAttempt, ...],
    outcome: AcquisitionOutcome,
    resolution: TargetSlotResolution | None = None,
    recorded_at_utc: str | None = None,
) -> None:
    commit_attempts_and_update_target(
        paths.run_state_path(str(row["run_id"])),
        attempts,
        outcome,
        resolution=resolution,
        recorded_at_utc=recorded_at_utc,
    )


def _cleanup_unreferenced_staging(paths: AcquisitionPaths, run_id: str) -> None:
    staging_root = paths.run_staging_root(run_id)
    if staging_root.is_symlink():
        raise ValueError("run staging directory is unsafe")
    if not staging_root.exists():
        return
    run_root = paths.run_dir(run_id).resolve()
    keep: set[Path] = set()
    with sqlite3.connect(
        f"file:{paths.run_state_path(run_id).resolve()}?mode=ro", uri=True
    ) as connection:
        for query in (
            "SELECT source_body_relative_path, selected_body_relative_path "
            "FROM target_state WHERE outcome = 'acquired'",
            "SELECT source_body_relative_path, selected_body_relative_path FROM attempts",
        ):
            for row in connection.execute(query):
                for relative in row:
                    if relative is not None:
                        candidate = (run_root / relative).resolve()
                        if candidate.is_relative_to(staging_root.resolve()):
                            keep.add(candidate)
    for candidate in staging_root.iterdir():
        if candidate.is_dir() and not candidate.is_symlink():
            continue
        if candidate.resolve() not in keep:
            candidate.unlink(missing_ok=True)


def execute_acquisition_run(
    run_id: str,
    *,
    retry_failures: bool,
    paths: AcquisitionPaths,
    policy: AcquisitionPolicy,
    transport: AcquisitionTransport,
    clock: Callable[[], datetime],
    confirm_stale_lock: bool = False,
) -> AcquisitionRunReport:
    parts = load_validated_work_order(paths, run_id)
    resources = derive_resources()
    bounded_workers = min(
        policy.requested_workers or resources.workers,
        resources.worker_ceiling,
    )
    if bounded_workers < 1:
        raise ValueError("resource-derived worker capacity is invalid")
    staging_root = paths.run_staging_root(run_id)
    attempted = 0
    processed = 0
    cancelled = False
    processing_counts: Counter[str] = Counter()
    processing_complete = False
    try:
        with RunLock(
            paths.run_lock_path(run_id),
            run_id,
            stale_local_lock_confirmed=confirm_stale_lock,
        ):
            relation_directory, relation_connection = _read_relation_spool(
                paths, run_id
            )
            try:
                run_root = paths.run_dir(run_id).resolve()
                if (
                    staging_root.is_symlink()
                    or (staging_root.exists() and not staging_root.is_dir())
                    or not staging_root.resolve().is_relative_to(run_root)
                ):
                    raise ValueError("run staging directory is unsafe")
                for row, state in iter_target_state_pairs(
                    paths.run_state_path(run_id),
                    iter_work_order_rows(parts),
                ):
                    if state is None or state.target_id != row["target_id"]:
                        raise ValueError("work-order targets are missing or duplicated")
                    if (
                        bool(row["executable"]) != state.executable
                        or row["skip_reason"] != state.skip_reason
                    ):
                        raise ValueError("work-order target disagrees with run state")
                    eligible = state.outcome == "pending" or (
                        retry_failures and state.outcome == "failed" and state.retryable
                    )
                    if eligible:
                        attempts, outcome, resolution, recorded_at = acquire_target(
                            row,
                            state,
                            run_id=run_id,
                            paths=paths,
                            policy=policy,
                            transport=transport,
                            clock=clock,
                        )
                        _commit(
                            paths,
                            row | {"run_id": run_id},
                            attempts,
                            outcome,
                            resolution,
                            recorded_at,
                        )
                        attempted += 1
                    fresh_state = get_target_state(
                        paths.run_state_path(run_id), str(row["target_id"])
                    )
                    if fresh_state is not None and fresh_state.outcome == "acquired":
                        if process_acquired_target(
                            row | {"run_id": run_id},
                            paths=paths,
                            retry_failures=retry_failures,
                            relation_connection=relation_connection,
                            operation_states_path=paths.run_state_path(run_id),
                        ):
                            processed += 1
                for operation_state in iter_operation_states(
                    paths.run_state_path(run_id)
                ):
                    processing_counts[_operation_status(operation_state)] += 1
                processing_complete = all(
                    status in _TERMINAL_OPERATION_STATUSES
                    for status in processing_counts
                )
            finally:
                relation_connection.close()
                relation_directory.cleanup()
    except KeyboardInterrupt:
        cancelled = True
    finally:
        try:
            close = getattr(transport, "close", None)
            if callable(close):
                close()
        finally:
            if staging_root.exists():
                _cleanup_unreferenced_staging(paths, run_id)
    counts = summarize_target_state(paths.run_state_path(run_id))
    status = inspect_run_state(
        run_id,
        database_path=paths.run_state_path(run_id),
        lock_path=paths.run_lock_path(run_id),
    )
    return AcquisitionRunReport(
        run_id=run_id,
        state=status.state,
        target_counts=counts.target_counts,
        attempted_count=attempted,
        retryable_failure_count=counts.retryable_failure_count,
        non_retryable_failure_count=counts.non_retryable_failure_count,
        cancelled=cancelled,
        processing_operation_counts=dict(sorted(processing_counts.items())),
        processing_attempted_target_count=processed,
        processing_complete=processing_complete,
        processing_success=(
            processing_complete
            and processing_counts.get("failed", 0) == 0
            and processing_counts.get("blocked", 0) == 0
            and processing_counts.get("unsupported", 0) == 0
        ),
    )


__all__ = ["AcquisitionTransport", "execute_acquisition_run"]
