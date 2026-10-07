"""Filing catalog and plan status reporting command."""

from __future__ import annotations

import argparse

from edgar_sec.foundation.runtime.render import KeyValueRow, render_output
from edgar_sec.pipelines.filing_catalog.discovery import status as build_status
from edgar_sec.pipelines.filing_catalog.paths import (
    resolve_filing_catalog_paths,
)

from .common import resolve_artifacts


def cmd_status(args: argparse.Namespace) -> int:
    """Report published catalogs and plans from manifests."""
    paths = resolve_filing_catalog_paths(resolve_artifacts(args.artifacts))
    status_data = build_status(paths)
    render_output(
        [
            KeyValueRow("catalog_count", str(status_data.get("catalog_count", 0))),
            KeyValueRow("plan_count", str(status_data.get("plan_count", 0))),
            KeyValueRow(
                "current_catalog_id",
                str(status_data.get("current_catalog_id") or "none"),
            ),
        ],
        title="Filing Catalog Status",
    )
    return 0
