from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime

from edgar_sec.pipelines.document_acquisition.commands.common import (
    _LazySecTransport,
    response_byte_limit,
    sec_transport_factory,
)
from edgar_sec.pipelines.document_acquisition.models import AcquisitionPolicy
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
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
    )
    payload = {
        "attempted_count": report.attempted_count,
        "cancelled": report.cancelled,
        "command": "run",
        "non_retryable_failure_count": report.non_retryable_failure_count,
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
            f"retain_response_evidence={args.retain_response_evidence}"
        )
    if report.cancelled:
        return 130
    return (
        1 if report.state in {"needs_retry", "complete_with_errors", "invalid"} else 0
    )
