"""Execute every pending chunk of a validated inventory run."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.pipelines.document_inventory.commands.common import (
    resolve_artifacts_root,
)
from edgar_sec.pipelines.document_inventory.coordinator import run_missing_accessions
from edgar_sec.pipelines.document_inventory.run_state import load_run_state


def cmd_run(args: Any) -> int:
    root = resolve_artifacts_root(args.artifacts_root)
    projection, run = load_run_state(root, args.run_id)
    paths = projection.paths
    identity = {
        "parent_snapshot_id": run.parent_snapshot_id,
        "canonical_cohort_id": run.canonical_cohort_id,
        "source_identity": run.source_identity,
        "parser_version": run.parser_version,
        "chunk_size": run.chunk_size,
        "refresh_mode": run.refresh_mode,
        "fetch_mode": run.fetch_mode,
        "fixture_id": run.fixture_id,
        "work_order_version": run.work_order_version,
    }
    summary = run_missing_accessions(
        paths.work_order_path(),
        identity,
        paths,
        http_client=getattr(args, "http_client", None),
        profile=getattr(args, "profile", None),
        workers=args.workers,
        retry_failures=args.retry_failures,
        stale_lock_confirmed=args.confirm_stale_lock,
    )
    if summary.cancelled:
        atomic_write_json(
            paths.cancelled_path(), {"run_id": summary.run_id, "cancelled": True}
        )
    else:
        paths.cancelled_path().unlink(missing_ok=True)
    payload = asdict(summary)
    payload["status"] = summary.status
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            f"Run {summary.run_id}: {summary.status}; "
            f"{summary.chunk_count} chunks, {summary.refusal_count} refused outcomes"
        )
    return 130 if summary.cancelled else 0
