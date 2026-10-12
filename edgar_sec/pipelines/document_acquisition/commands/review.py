from __future__ import annotations

import argparse
import json

from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.review_artifacts.builder import (
    build_review_artifacts,
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
        "replay_failures": summary.replay_failure,
        "execution_errors": summary.execution_error,
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            f"review {result.review_id}: {summary.completed}/{summary.total} complete, "
            f"replay failures={summary.replay_failure}, "
            f"execution errors={summary.execution_error}"
        )
    return result.exit_code


__all__ = ["cmd_review_artifacts"]
