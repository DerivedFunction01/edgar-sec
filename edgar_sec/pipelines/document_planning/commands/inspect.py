"""Validate and report a published document-target plan."""

from __future__ import annotations

import argparse
import json

from edgar_sec.foundation.runtime.render import (
    Grid,
    KeyValueRow,
    RenderComponent,
    render_output,
)
from edgar_sec.pipelines.document_planning.discovery import (
    DocumentPlanError,
    read_published_plan,
)
from edgar_sec.pipelines.document_planning.paths import resolve_document_planning_paths


def cmd_inspect(args: argparse.Namespace) -> int:
    paths = resolve_document_planning_paths(artifacts_root=args.artifacts or None)
    try:
        plan = read_published_plan(args.plan_id, paths)
    except (DocumentPlanError, OSError, ValueError) as error:
        print(f"plan inspection failed: {error}")
        return 2
    report = {
        "plan_id": plan.plan_id,
        "plan_digest": plan.manifest["plan_digest"],
        "profile_id": plan.manifest["profile_id"],
        "profile_version": plan.manifest["profile_version"],
        "catalog_plan_id": plan.manifest["catalog_plan_id"],
        "catalog_plan_digest": plan.manifest["catalog_plan_digest"],
        "inventory_snapshot_id": plan.manifest["inventory_snapshot_id"],
        "inventory_snapshot_digest": plan.manifest["inventory_snapshot_digest"],
        "distinct_accession_coverage": plan.manifest["distinct_accession_coverage"],
        "target_row_count": plan.manifest["target_row_count"],
        "status_counts": plan.manifest["status_counts"],
        "origin_counts": plan.manifest["origin_counts"],
        "reason_counts": plan.manifest["reason_counts"],
        "parts": plan.manifest["parts"],
    }
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        components: list[RenderComponent] = [
            KeyValueRow(
                "catalog plan",
                f"{report['catalog_plan_id']} ({report['catalog_plan_digest']})",
            ),
            KeyValueRow(
                "inventory snapshot",
                f"{report['inventory_snapshot_id']} "
                f"({report['inventory_snapshot_digest']})",
            ),
            KeyValueRow("coverage", str(report["distinct_accession_coverage"])),
            KeyValueRow("target rows", f"{report['target_row_count']:,}"),
            KeyValueRow("statuses", str(report["status_counts"])),
            KeyValueRow("origins", str(report["origin_counts"])),
            KeyValueRow("reasons", str(report["reason_counts"])),
        ]
        if report["parts"]:
            components.append(
                Grid(
                    headers=("Part", "Rows", "SHA256"),
                    rows=tuple(
                        (str(part["path"]), str(part["rows"]), str(part["sha256"]))
                        for part in report["parts"]
                    ),
                )
            )
        render_output(components, title=f"validated document plan {plan.plan_id}")
    return 0


__all__ = ["cmd_inspect"]
