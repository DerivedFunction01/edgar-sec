"""Inventory build command."""

from __future__ import annotations

import argparse
import json

from edgar_sec.foundation.runtime.render import KeyValueRow, render_output
from edgar_sec.pipelines.document_inventory.snapshot import builder

from .common import resolve_artifacts_root


def cmd_build(args: argparse.Namespace) -> int:
    """Build and publish an immutable inventory snapshot."""
    root = resolve_artifacts_root(args.artifacts_root)
    publication = builder.build_inventory(
        args.catalog_plan,
        base_snapshot_id=args.base_snapshot_id,
        explicit_refresh=args.explicit_refresh,
        chunk_size=args.chunk_size,
        retry_failures=args.retry_failures,
        workers=args.workers,
        artifacts_root=root,
        branch_name=args.branch or "main",
    )
    payload = {
        "status": publication.status,
        "snapshot_id": (
            publication.snapshot.snapshot_id if publication.snapshot else None
        ),
        "reason": publication.reason,
    }

    if getattr(args, "json", False):
        print(
            json.dumps(
                {"schema_version": 1, "command": "inventory build", **payload},
                sort_keys=True,
                ensure_ascii=False,
            )
        )
    else:
        render_output(
            [
                KeyValueRow("status", str(publication.status)),
                KeyValueRow(
                    "snapshot_id",
                    str(publication.snapshot.snapshot_id)
                    if publication.snapshot
                    else "none",
                ),
                KeyValueRow("reason", str(publication.reason or "none")),
            ],
            title="Inventory Build",
        )

    return 0 if not publication.was_failed else 1
