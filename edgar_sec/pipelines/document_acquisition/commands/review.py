from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from edgar_sec.infra.storage.review.diff import compare_review_runs
from edgar_sec.infra.storage.review.paths import (
    ReviewPaths,
    new_diff_dir,
    review_runs_root,
)
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.review_artifacts.builder import (
    build_review_artifacts,
)
from edgar_sec.pipelines.document_acquisition.review_artifacts.analyzer import (
    analyze_review_runs,
)


def cmd_review_artifacts(args: argparse.Namespace) -> int:
    paths = resolve_acquisition_paths(artifacts_root=args.artifacts_root or None)
    result = build_review_artifacts(
        args.fixture,
        args.output,
        paths=paths,
        capture_id=args.capture_id,
        target_id=args.target_id,
        accessions=args.accessions,
        limit=args.limit,
        workers=args.workers,
    )
    summary = result.summary
    payload = {
        "schema_version": 1,
        "command": "review generate",
        "review_id": result.review_id,
        "fixture_id": args.fixture,
        "output": str(result.output_root),
        "total": summary.total,
        "completed": summary.completed,
        "fixture_verification_failures": summary.fixture_verification_failure,
        "execution_errors": summary.execution_error,
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            f"review {result.review_id}: {summary.completed}/{summary.total} complete, "
            f"fixture verification failures={summary.fixture_verification_failure}, "
            f"execution errors={summary.execution_error}"
        )
    return result.exit_code


def _review_run_path(value: str, artifacts_root: str | None) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.exists():
        candidate = (
            review_runs_root(
                artifacts_root or resolve_acquisition_paths().artifacts_root,
                "document_acquisition",
            )
            / value
        )
    return candidate


def cmd_review_analyze(args: argparse.Namespace) -> int:
    runs = tuple(_review_run_path(value, args.artifacts) for value in args.run)
    report = analyze_review_runs(
        runs, output=Path(args.output) if args.output else None
    )
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        for run in report["runs"]:
            statuses = ", ".join(
                f"{name}={count}" for name, count in run["case_status_counts"].items()
            )
            operation_statuses = (
                ", ".join(
                    f"{name}={count}"
                    for name, count in run["operation_status_counts"].items()
                )
                or "none"
            )
            print(
                f"review {run['review_id']}: {run['total_cases']} cases; "
                f"{statuses}; operations: {operation_statuses}"
            )
    return 0


def cmd_review_compare(args: argparse.Namespace) -> int:
    from edgar_sec.pipelines.document_acquisition.review_artifacts.adapter import (
        AcquisitionReviewAdapter,
    )

    base_dir = _review_run_path(args.base, args.artifacts)
    new_dir = _review_run_path(args.new, args.artifacts)
    analyze_review_runs((base_dir, new_dir))
    paths = resolve_acquisition_paths(artifacts_root=args.artifacts or None)
    output_dir = (
        Path(args.output)
        if args.output
        else new_diff_dir(
            review_runs_root(paths.artifacts_root, "document_acquisition")
        )
    )
    summary = compare_review_runs(
        base_dir=base_dir,
        new_dir=new_dir,
        output_dir=output_dir,
        adapter=AcquisitionReviewAdapter(),
        max_display=args.max_display,
    )
    result: dict[str, Any] = {
        "base_run": summary.base_run,
        "new_run": summary.new_run,
        "total_cases": summary.total_cases,
        "unchanged": summary.unchanged_count,
        "changed": summary.changed_count,
        "added": summary.added_count,
        "removed": summary.removed_count,
        "output_dir": str(output_dir),
    }
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(ReviewPaths(output_dir).summary_file.read_text(encoding="utf-8"))
    return 0


__all__ = ["cmd_review_analyze", "cmd_review_artifacts", "cmd_review_compare"]
