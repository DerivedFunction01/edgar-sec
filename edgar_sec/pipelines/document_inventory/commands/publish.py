"""Publish a completed persisted inventory run without network access."""

from __future__ import annotations

import json
from typing import Any

from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.publication import StaleParentError
from edgar_sec.pipelines.document_inventory.commands.common import (
    resolve_artifacts_root,
)
from edgar_sec.pipelines.document_inventory.paths import InventoryPaths
from edgar_sec.pipelines.document_inventory.run_lock import RunLock
from edgar_sec.pipelines.document_inventory.run_state import (
    load_run_state,
    load_run_status,
)
from edgar_sec.pipelines.document_inventory.snapshot.writer import (
    publish_committed_chunks,
)


def cmd_publish(args: Any) -> int:
    root = resolve_artifacts_root(args.artifacts_root)
    before = load_run_status(root, args.run_id)
    if not before.valid:
        raise ValueError(before.error or "run state is invalid")
    if before.state == "published":
        payload = {
            "status": "already_published",
            "run_id": args.run_id,
            "snapshot_id": before.published_snapshot_id,
            "reason": None,
        }
        if args.json:
            print(json.dumps(payload, sort_keys=True))
        else:
            print(
                f"Run {args.run_id} was already published as "
                f"{before.published_snapshot_id}"
            )
        return 0
    if before.state != "ready":
        raise ValueError(f"run is not publishable: {before.state}")
    if not before.can_publish:
        raise ValueError("run has pending chunks or refused outcomes")
    if (
        args.expected_branch_tip is not None
        and args.expected_branch_tip != before.base_snapshot_id
    ):
        raise ValueError("expected branch tip differs from the run's pinned base")

    projection, run = load_run_state(root, args.run_id)
    inventory_paths = InventoryPaths(root)
    catalog = DAGCatalog(inventory_paths.snapshots_root)
    pointer = catalog.read_pointer(args.branch)
    current_tip = str(pointer["snapshot_id"]) if pointer else None
    if current_tip != projection.base_snapshot_id:
        raise StaleParentError(
            f"branch {args.branch!r} is at {current_tip!r}; "
            f"run is pinned to {projection.base_snapshot_id!r}"
        )

    with RunLock(projection.paths, stale_lock_confirmed=False):
        current = load_run_status(root, args.run_id, allow_locked=True)
        if (
            not current.valid
            or current.state != "ready"
            or current.outstanding_chunks
            or current.retryable_failures
            or current.refused_outcomes
            or current.published_snapshot_id
        ):
            raise ValueError("run changed or is no longer publishable")
        publication = publish_committed_chunks(
            projection.paths,
            run,
            cohort_accessions_path=projection.paths.cohort_accessions_path(),
            cohort_sources_path=projection.paths.cohort_sources_path(),
            expected_parent_snapshot_id=projection.base_snapshot_id,
            branch_name=args.branch,
            expected_branch_tip=projection.base_snapshot_id,
            profile=getattr(args, "profile", None),
        )
    payload = {
        "status": publication.status,
        "run_id": args.run_id,
        "snapshot_id": (
            publication.snapshot.snapshot_id if publication.snapshot else None
        ),
        "reason": publication.reason,
    }
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    else:
        snapshot_id = payload["snapshot_id"] or "(no-op)"
        print(f"Publish {args.run_id}: {publication.status}; snapshot {snapshot_id}")
    return 1 if publication.status == "failed" else 0
