from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime

from tqdm import tqdm

from edgar_sec.foundation.runtime.progress import make_tqdm_callback
from edgar_sec.pipelines.document_acquisition.commands.common import (
    _LazySecTransport,
    response_byte_limit,
    sec_transport_factory,
)
from edgar_sec.pipelines.document_acquisition.models import AcquisitionPolicy
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.run_state.store import (
    summarize_target_state,
)
from edgar_sec.pipelines.document_acquisition.runner import execute_acquisition_run


def cmd_run(args: argparse.Namespace) -> int:
    try:
        max_response_bytes = response_byte_limit(args.max_response_bytes)
    except (KeyError, TypeError, ValueError) as error:
        payload = {"command": "run", "error": str(error), "status": "error"}
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"run failed: {error}", file=sys.stderr)
        return 1

    paths = resolve_acquisition_paths(artifacts_root=args.artifacts)
    state_path = paths.run_state_path(args.run_id)
    total_targets: int | None = None
    if state_path.is_file():
        try:
            counts = summarize_target_state(state_path)
            total_targets = sum(counts.target_counts.values())
        except Exception:
            total_targets = None

    show_progress = (
        not getattr(args, "json", False)
        and not getattr(args, "no_progress", False)
        and sys.stderr.isatty()
    )
    progress_bar = (
        tqdm(
            total=total_targets,
            desc="Acquisition",
            unit="target",
            dynamic_ncols=True,
        )
        if show_progress
        else None
    )
    try:
        report = execute_acquisition_run(
            args.run_id,
            retry_failures=args.retry_failures,
            paths=paths,
            policy=AcquisitionPolicy(
                max_response_bytes=max_response_bytes,
                requested_workers=args.workers,
                retain_response_evidence=args.retain_response_evidence,
            ),
            transport=_LazySecTransport(sec_transport_factory),
            clock=lambda: datetime.now(UTC),
            confirm_stale_lock=args.confirm_stale_lock,
            progress_callback=(
                make_tqdm_callback(progress_bar) if progress_bar is not None else None
            ),
        )
    finally:
        if progress_bar is not None:
            progress_bar.close()
    payload = {
        "attempted_count": report.attempted_count,
        "cancelled": report.cancelled,
        "command": "run",
        "non_retryable_failure_count": report.non_retryable_failure_count,
        "processing": {
            "attempted_target_count": report.processing_attempted_target_count,
            "complete": report.processing_complete,
            "operation_counts": dict(report.processing_operation_counts),
            "success": report.processing_success,
        },
        "retain_response_evidence": args.retain_response_evidence,
        "retryable_failure_count": report.retryable_failure_count,
        "run_id": report.run_id,
        "state": report.state,
        "target_counts": dict(report.target_counts),
        "status": "cancelled" if report.cancelled else "complete",
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            f"run {report.run_id}: state={report.state}, "
            f"attempted={report.attempted_count}, "
            f"pending={report.target_counts.get('pending', 0)}, "
            f"retryable_failures={report.retryable_failure_count}, "
            f"terminal_failures={report.non_retryable_failure_count}, "
            f"processed_targets={report.processing_attempted_target_count}, "
            f"processing_operation_counts={report.processing_operation_counts}, "
            f"processing_complete={report.processing_complete}, "
            f"processing_success={report.processing_success}, "
            f"retain_response_evidence={args.retain_response_evidence}"
        )
    if report.cancelled:
        return 130
    return (
        1
        if report.state in {"needs_retry", "complete_with_errors", "invalid"}
        or not report.processing_success
        else 0
    )
