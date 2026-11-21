"""Inspect a pinned inventory snapshot without changing its DAG."""

from __future__ import annotations

import argparse
import json

from edgar_sec.pipelines.document_inventory.commands.common import (
    resolve_artifacts_root,
)
from edgar_sec.pipelines.document_inventory.paths import InventoryPaths
from edgar_sec.pipelines.document_inventory.snapshot.inspect import inspect_snapshot


def cmd_inspect_snapshot(args: argparse.Namespace) -> int:
    paths = InventoryPaths(resolve_artifacts_root(args.artifacts_root))
    try:
        report = inspect_snapshot(paths, args.snapshot, branch=args.branch)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"snapshot inspection failed: {error}")
        return 2
    if args.json:
        print(json.dumps(report, sort_keys=True))
    else:
        print(f"validated inventory snapshot {report['snapshot_id']}")
        print(f"  manifest SHA-256  {report['manifest_sha256']}")
        print(f"  lineage           {report['lineage']}")
        print(f"  active rows       {report['active_row_counts']}")
        print(f"  form/year counts  {report['counts_by_form_filing_year']}")
        print(f"  verified parts    {len(report['parts'])}")
    return 0


__all__ = ["cmd_inspect_snapshot"]
