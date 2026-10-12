from __future__ import annotations

import argparse
import json

from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths


def cmd_process(args: argparse.Namespace) -> int:
    from edgar_sec.pipelines.document_acquisition.processing_run import (
        execute_processing_run,
    )

    paths = resolve_acquisition_paths(artifacts_root=args.artifacts)
    summary = execute_processing_run(
        args.run_id,
        paths,
        retry_failures=args.retry_failures,
        workers=args.workers,
    )
    if args.json:
        print(json.dumps(summary, sort_keys=True))
    else:
        print(
            " ".join(
                f"{key}={json.dumps(value, sort_keys=True)}"
                for key, value in sorted(summary.items())
            )
        )
    return 0 if summary.get("success") else 1
