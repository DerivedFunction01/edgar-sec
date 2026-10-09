"""Create a deterministic document-target plan."""

from __future__ import annotations

import argparse
import json

from edgar_sec.pipelines.document_planning.paths import resolve_document_planning_paths
from edgar_sec.pipelines.document_planning.planner import (
    DocumentPlanningError,
    create_document_plan,
)
from edgar_sec.pipelines.document_planning.profiles import (
    get_or_create_baseline_profile,
)


def cmd_plan(args: argparse.Namespace) -> int:
    paths = resolve_document_planning_paths(artifacts_root=args.artifacts or None)
    # Resolve profile ID from either explicit --profile-id or auto-generated baseline
    profile_id = (
        args.profile_id
        or get_or_create_baseline_profile(paths.profiles_root).profile_id
    )
    try:
        result = create_document_plan(
            args.catalog_plan,
            args.profile_id,
            args.inventory,
            paths,
        )
    except (DocumentPlanningError, OSError, ValueError) as error:
        print(f"planning refused: {error}")
        return 2
    coverage = result.manifest["distinct_accession_coverage"]
    summary = {
        "plan_id": result.plan_id,
        "plan_path": str(result.root),
        "reused": result.reused,
        "catalog_plan_id": result.manifest["catalog_plan_id"],
        "catalog_plan_digest": result.manifest["catalog_plan_digest"],
        "inventory_snapshot_id": result.manifest["inventory_snapshot_id"],
        "inventory_snapshot_digest": result.manifest["inventory_snapshot_digest"],
        "target_row_count": result.manifest["target_row_count"],
        "distinct_accession_coverage": coverage,
        "status_counts": result.manifest["status_counts"],
    }
    if args.json:
        print(json.dumps(summary, sort_keys=True))
    else:
        print(f"published document plan {result.plan_id}")
        print(f"  target rows       {summary['target_row_count']:,}")
        print(f"  catalog plan      {summary['catalog_plan_id']}")
        if summary["inventory_snapshot_id"]:
            print(f"  inventory snapshot {summary['inventory_snapshot_id']}")
        print(f"  accession coverage {coverage}")
        print(f"  status counts      {summary['status_counts']}")
        print(f"  path               {summary['plan_path']}")
    return 0


__all__ = ["cmd_plan"]
