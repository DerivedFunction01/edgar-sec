"""Project published catalog plans into resumable inventory runs."""

from __future__ import annotations

import json
from typing import Any

import pyarrow.parquet as pq

from edgar_sec.pipelines.document_inventory.commands.common import (
    resolve_artifacts_root,
)
from edgar_sec.pipelines.document_inventory.snapshot.projection import (
    project_catalog_plan,
)
from edgar_sec.pipelines.document_inventory.run_manifest import read_run_manifest


def cmd_project(args: Any) -> int:
    projection = project_catalog_plan(
        args.catalog_plan,
        artifacts_root=resolve_artifacts_root(args.artifacts_root),
        base_snapshot_id=args.base_snapshot_id,
        branch_name=args.branch,
        chunk_size=args.chunk_size,
        explicit_refresh=args.explicit_refresh,
        profile=getattr(args, "profile", None),
    )
    run = read_run_manifest(projection.paths)
    if run is None:
        raise ValueError(f"projected run manifest is missing: {projection.run_id}")
    payload = {
        "status": "projected",
        "run_id": projection.run_id,
        "catalog_plan_id": projection.catalog_plan_id,
        "branch": args.branch,
        "base_snapshot_id": projection.base_snapshot_id,
        "cohort_accession_rows": pq.ParquetFile(
            projection.paths.cohort_accessions_path()
        ).metadata.num_rows,
        "work_order_rows": projection.work_order_rows,
        "work_order_digest": projection.work_order_digest,
        "chunk_size": run.chunk_size,
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(
            f"Projected run {projection.run_id}: "
            f"{payload['cohort_accession_rows']} accessions, "
            f"{projection.work_order_rows} index pages, "
            f"chunk size {run.chunk_size}, branch {args.branch}, "
            f"base {projection.base_snapshot_id or '(empty)'}"
        )
    return 0
