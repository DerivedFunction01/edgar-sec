from __future__ import annotations

import argparse
import json
import sys

from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.plan_projection.project import (
    AcquisitionProjectError,
    project_acquisition_run,
)


def cmd_project(args: argparse.Namespace) -> int:
    paths = resolve_acquisition_paths(artifacts_root=args.artifacts)
    try:
        result = project_acquisition_run(args.plan_id, paths=paths)
    except (AcquisitionProjectError, OSError, ValueError) as error:
        payload = {
            "command": "project",
            "error": str(error),
            "status": "error",
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"project failed: {error}", file=sys.stderr)
        return 1
    payload = {
        "command": "project",
        "executable_count": result.executable_count,
        "reused": result.reused,
        "run_id": result.run_id,
        "skipped_count": result.skipped_count,
        "status": "ready",
        "target_plan_digest": result.manifest["target_plan_digest"],
        "target_plan_id": result.manifest["target_plan_id"],
        "work_order_sha256": result.work_order_sha256,
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            f"projected {result.run_id}: {result.executable_count} executable, "
            f"{result.skipped_count} skipped, reused={result.reused}"
        )
    return 0
