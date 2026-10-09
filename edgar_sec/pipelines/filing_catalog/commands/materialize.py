"""Catalog materialization command."""

from __future__ import annotations

import argparse
import sys

from edgar_sec.foundation.runtime.render import KeyValueRow, render_output
from edgar_sec.pipelines.filing_catalog.catalog_job import (
    CatalogError,
    materialize,
)

from .common import emit_progress, resolve_artifacts


def cmd_materialize(args: argparse.Namespace) -> int:
    """Build a catalog snapshot from a metadata snapshot."""
    try:
        manifest = materialize(
            args.source or None,
            resolve_artifacts(args.artifacts),
            source_manifest=args.source_manifest or None,
            progress=emit_progress,
            branch_name=args.branch or "main",
        )
    except CatalogError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    render_output(
        [
            KeyValueRow("catalog_id", manifest.get("catalog_id", "")),
            KeyValueRow("source_snapshot_id", manifest.get("source_snapshot_id", "")),
            KeyValueRow("target_row_count", str(manifest.get("target_row_count", 0))),
            KeyValueRow("form_count", str(manifest.get("form_count", 0))),
            KeyValueRow("partition_count", str(manifest.get("partition_count", 0))),
        ],
        title=f"Catalog Materialized ({manifest.get('catalog_id', '')[:8]})",
    )
    return 0
