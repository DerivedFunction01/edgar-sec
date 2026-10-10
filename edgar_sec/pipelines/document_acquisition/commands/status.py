from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import asdict, replace

from edgar_sec.pipelines.document_acquisition.models import AcquisitionStatusReport
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.run_state.evidence import (
    list_target_attempts,
)
from edgar_sec.pipelines.document_acquisition.run_state.store import (
    get_target_state,
    inspect_run_state,
)
from edgar_sec.pipelines.document_acquisition.run_validation import (
    load_validated_work_order,
)


def _run_ids(paths) -> tuple[str, ...]:
    root = paths.runs_root
    if root.is_symlink():
        raise ValueError("acquisition runs root is unsafe")
    if not root.exists():
        return ()
    if not root.is_dir():
        raise ValueError("acquisition runs root is not a directory")
    run_ids = []
    for candidate in root.iterdir():
        if candidate.is_symlink() or not candidate.is_dir():
            continue
        try:
            paths.run_dir(candidate.name)
        except ValueError:
            continue
        run_ids.append(candidate.name)
    return tuple(sorted(run_ids))


def _inspect_run(paths, run_id: str) -> AcquisitionStatusReport:
    try:
        load_validated_work_order(paths, run_id)
    except (OSError, sqlite3.Error, TypeError, ValueError, KeyError) as error:
        report = inspect_run_state(
            run_id,
            database_path=paths.run_state_path(run_id),
            lock_path=paths.run_lock_path(run_id),
        )
        if report.state == "invalid":
            return report
        return replace(report, state="invalid", invalid_reason=str(error))
    return inspect_run_state(
        run_id,
        database_path=paths.run_state_path(run_id),
        lock_path=paths.run_lock_path(run_id),
    )


def _status_mapping(report: AcquisitionStatusReport) -> dict[str, object]:
    active_lock = report.active_lock
    return {
        "active_lock": (
            {
                "host": active_lock.host,
                "pid": active_lock.pid,
                "started_at_utc": active_lock.started_at_utc,
            }
            if active_lock
            else None
        ),
        "invalid_reason": report.invalid_reason,
        "non_retryable_failure_count": report.non_retryable_failure_count,
        "retryable_failure_count": report.retryable_failure_count,
        "run_id": report.run_id,
        "state": report.state,
        "target_counts": dict(report.target_counts),
    }


def _status_safe_mapping(value) -> dict[str, object]:
    return {key: item for key, item in asdict(value).items() if "path" not in key}


def cmd_status(args: argparse.Namespace) -> int:
    try:
        if args.target_id and not args.run_id:
            raise ValueError("--target-id requires --run-id")
        paths = resolve_acquisition_paths(artifacts_root=args.artifacts)
        if args.target_id:
            report = _inspect_run(paths, args.run_id)
            if report.state == "invalid":
                raise ValueError(report.invalid_reason or "run state is invalid")
            database_path = paths.run_state_path(args.run_id)
            target = get_target_state(database_path, args.target_id)
            if target is None:
                raise ValueError(f"unknown target {args.target_id!r}")
            attempts = list_target_attempts(database_path, args.target_id)
            attempt_rows = [_status_safe_mapping(attempt) for attempt in attempts]
            payload = {
                "attempts": attempt_rows,
                "command": "status",
                "run_id": args.run_id,
                "status": "ok",
                "target_id": target.target_id,
                "target_outcome": target.outcome,
            }
            if args.json:
                print(json.dumps(payload, sort_keys=True))
            else:
                print(f"{args.run_id}: target {target.target_id} ({target.outcome})")
                for attempt in attempt_rows:
                    print("  " + json.dumps(attempt, sort_keys=True))
            return 0

        run_ids = (args.run_id,) if args.run_id else _run_ids(paths)
        reports = [_inspect_run(paths, run_id) for run_id in run_ids]
    except (OSError, sqlite3.Error, ValueError) as error:
        payload = {"command": "status", "error": str(error), "status": "error"}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"status failed: {error}", file=sys.stderr)
        return 1
    invalid = any(report.state == "invalid" for report in reports)
    payload = {
        "command": "status",
        "runs": [_status_mapping(report) for report in reports],
        "status": "invalid" if invalid else "ok",
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    elif not reports:
        print("No acquisition runs found.")
    else:
        for report in reports:
            counts = ", ".join(
                f"{name}={count}"
                for name, count in sorted(report.target_counts.items())
                if count
            )
            print(f"{report.run_id}: {report.state}; {counts or 'no targets'}")
            if report.invalid_reason:
                print(f"  invalid: {report.invalid_reason}")
    return 1 if invalid else 0
