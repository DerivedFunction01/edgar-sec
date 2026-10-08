"""Review artifacts command."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from edgar_sec.foundation.runtime.render import KeyValueRow, render_output
from edgar_sec.pipelines.document_inventory.paths import resolve_index_fixture_paths
from edgar_sec.pipelines.document_inventory.review_artifacts.builder import (
    build_review_artifacts,
)

from .common import resolve_artifacts_root


def cmd_review_artifacts(args: argparse.Namespace) -> int:
    """Build offline parser review artifacts from index fixtures."""
    root = resolve_artifacts_root(args.artifacts_root)
    fixture = resolve_index_fixture_paths(root, args.fixture)
    result = build_review_artifacts(
        fixture,
        Path(args.output).expanduser().resolve(),
        accessions=args.accession,
        limit=args.limit,
        workers=args.workers,
    )
    summary = result.summary
    payload = {
        "review_id": result.review_id,
        "fixture_id": args.fixture,
        "output": str(result.output_root),
        "total": summary.total,
        "parsed": summary.parsed,
        "unrecognized": summary.unrecognized,
        "parse_failures": summary.parse_failure,
        "execution_errors": summary.execution_error,
        "entries_total": summary.entries_total,
        "failed": summary.failed,
    }

    if getattr(args, "json", False):
        print(
            json.dumps(
                {"schema_version": 1, "command": "review-artifacts", **payload},
                sort_keys=True,
                ensure_ascii=False,
            )
        )
    else:
        render_output(
            [
                KeyValueRow("review_id", str(result.review_id)),
                KeyValueRow("fixture_id", str(args.fixture)),
                KeyValueRow("output", str(result.output_root)),
                KeyValueRow("total", str(summary.total)),
                KeyValueRow("parsed", str(summary.parsed)),
                KeyValueRow("unrecognized", str(summary.unrecognized)),
                KeyValueRow("parse_failures", str(summary.parse_failure)),
                KeyValueRow("execution_errors", str(summary.execution_error)),
                KeyValueRow("entries_total", str(summary.entries_total)),
                KeyValueRow("failed", str(summary.failed)),
            ],
            title=f"Review Artifacts ({args.fixture})",
        )

    return result.exit_code
