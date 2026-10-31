"""Publish a completed acquisition run to the snapshot DAG."""

from __future__ import annotations

import argparse
import json
import sys

from edgar_sec.infra.storage.dag.publication import StaleParentError
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths
from edgar_sec.pipelines.document_acquisition.snapshot.errors import SnapshotError
from edgar_sec.pipelines.document_acquisition.snapshot.writer import (
    publish_acquisition_run,
)


def cmd_publish(args: argparse.Namespace) -> int:
    """Publish a completed persisted acquisition run to the snapshot DAG."""
    paths = resolve_acquisition_paths(artifacts_root=args.artifacts)
    try:
        publication = publish_acquisition_run(
            paths,
            args.run_id,
            branch_name=getattr(args, "branch", "main"),
            expected_branch_tip=getattr(args, "expected_branch_tip", None),
            allow_errors=getattr(args, "allow_errors", False),
        )
    except (SnapshotError, StaleParentError, OSError, ValueError) as error:
        payload = {
            "command": "publish",
            "error": str(error),
            "status": "error",
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(f"publish failed: {error}", file=sys.stderr)
        return 1

    payload = {
        "command": "publish",
        "reason": publication.reason,
        "run_id": publication.run_id,
        "snapshot_id": publication.snapshot_id,
        "status": publication.status,
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        snapshot_id = publication.snapshot_id or "(no-op)"
        print(
            f"Publish {publication.run_id}: {publication.status}; "
            f"snapshot {snapshot_id}"
        )
    return 1 if publication.status == "failed" else 0


__all__ = ["cmd_publish"]
