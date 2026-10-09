"""Inspect persisted inventory run progress without modifying it."""

from __future__ import annotations

import json
from typing import Any

from edgar_sec.pipelines.document_inventory.commands.common import (
    resolve_artifacts_root,
)
from edgar_sec.pipelines.document_inventory.run_state import (
    discover_run_statuses,
    load_run_status,
)


def cmd_status(args: Any) -> int:
    root = resolve_artifacts_root(args.artifacts_root)
    statuses = (
        (load_run_status(root, args.run_id),)
        if args.run_id
        else discover_run_statuses(root)
    )
    if args.json:
        print(
            json.dumps(
                {"status": "ok", "runs": [item.to_dict() for item in statuses]},
                sort_keys=True,
            )
        )
    elif not statuses:
        print("No projected inventory runs")
    else:
        for item in statuses:
            details = []
            if item.locked:
                owner = item.lock_metadata or {}
                details.append(
                    f"lock pid={owner.get('pid', '?')} host={owner.get('host', '?')}"
                )
            if item.error:
                details.append(item.error)
            suffix = f"; {'; '.join(details)}" if details else ""
            print(
                f"{item.run_id}: {item.state}; "
                f"chunks {item.committed_chunks}/{item.expected_chunks}; "
                f"pending {item.pending_accessions} accessions/"
                f"{item.outstanding_chunks} chunks; "
                f"failures {item.retryable_failures + item.refused_outcomes}; "
                f"base {item.base_snapshot_id or '(empty)'}{suffix}"
            )
    return 1 if args.run_id and statuses and not statuses[0].valid else 0
