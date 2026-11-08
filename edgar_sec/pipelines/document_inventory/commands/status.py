"""Inspect persisted inventory run progress without modifying it."""

from __future__ import annotations

import json
from typing import Any

from edgar_sec.foundation.runtime.render import (
    Grid,
    KeyValueRow,
    ProseRow,
    RenderComponent,
    render_output,
)
from edgar_sec.pipelines.document_inventory.commands.common import (
    resolve_artifacts_root,
)
from edgar_sec.pipelines.document_inventory.run_state.run_state import (
    InventoryRunStatus,
    discover_run_statuses,
    load_run_status,
)


def _lock_value(item: InventoryRunStatus) -> str:
    if not item.locked:
        return "none"
    owner = item.lock_metadata or {}
    return f"pid={owner.get('pid', '?')} host={owner.get('host', '?')}"


def _failures_value(item: InventoryRunStatus) -> str:
    return str(item.retryable_failures + item.refused_outcomes)


def _base_value(item: InventoryRunStatus) -> str:
    return item.base_snapshot_id or "(empty)"


def _status_components(
    statuses: tuple[InventoryRunStatus, ...],
) -> list[RenderComponent]:
    if not statuses:
        return [ProseRow("No projected inventory runs")]
    if len(statuses) == 1:
        item = statuses[0]
        rows: list[RenderComponent] = [
            KeyValueRow("run_id", item.run_id),
            KeyValueRow("state", item.state),
            KeyValueRow("valid", str(item.valid)),
        ]
        if item.error:
            rows.append(KeyValueRow("error", item.error))
        rows.extend(
            [
                KeyValueRow("catalog_plan_id", item.catalog_plan_id or ""),
                KeyValueRow("base_snapshot_id", _base_value(item)),
                KeyValueRow("work_order_rows", str(item.work_order_rows)),
                KeyValueRow("committed_chunks", str(item.committed_chunks)),
                KeyValueRow("expected_chunks", str(item.expected_chunks)),
                KeyValueRow("outstanding_chunks", str(item.outstanding_chunks)),
                KeyValueRow("pending_accessions", str(item.pending_accessions)),
                KeyValueRow("invalid_chunks", str(item.invalid_chunks)),
                KeyValueRow("retryable_failures", str(item.retryable_failures)),
                KeyValueRow("refused_outcomes", str(item.refused_outcomes)),
                KeyValueRow("failures", _failures_value(item)),
                KeyValueRow("locked", str(item.locked)),
                KeyValueRow("lock", _lock_value(item)),
                KeyValueRow("published_snapshot_id", item.published_snapshot_id or ""),
            ]
        )
        return rows
    return [
        Grid(
            headers=(
                "run_id",
                "state",
                "chunks",
                "pending_accessions",
                "outstanding_chunks",
                "failures",
                "base",
                "lock",
                "error",
            ),
            rows=tuple(
                (
                    item.run_id,
                    item.state,
                    f"{item.committed_chunks}/{item.expected_chunks}",
                    str(item.pending_accessions),
                    str(item.outstanding_chunks),
                    _failures_value(item),
                    _base_value(item),
                    _lock_value(item) if item.locked else "",
                    item.error or "",
                )
                for item in statuses
            ),
        )
    ]


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
    else:
        render_output(_status_components(statuses), title="Inventory Status")
    return 1 if args.run_id and statuses and not statuses[0].valid else 0
