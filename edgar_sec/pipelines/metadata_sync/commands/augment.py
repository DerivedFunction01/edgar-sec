"""Snapshot cohort augmentation command."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from edgar_sec.foundation.runtime.render import (
    KeyValueRow,
    ProseRow,
    render_output,
)
from edgar_sec.pipelines.metadata_sync.augmentation import (
    augment,
    augment_from_roster,
    preflight_augment,
)
from edgar_sec.pipelines.metadata_sync.options import (
    PlanOptions,
    SelectedCohort,
    resolve_cohort,
)
from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths
from edgar_sec.pipelines.metadata_sync.progress import AugmentProgress
from edgar_sec.pipelines.metadata_sync.run_lock import RunLock
from edgar_sec.pipelines.metadata_sync.sec_client import SubmissionsClient
from edgar_sec.pipelines.metadata_sync.snapshot import read_snapshot_parts

from .client import build_client


def cmd_augment(
    options: PlanOptions,
    *,
    base_snapshot_id: str,
    new_snapshot_id: str = "",
    workers: int | None = None,
    lineage: dict[str, str] | None = None,
    client: SubmissionsClient | None = None,
) -> int:
    """Add only newly requested CIKs to a published snapshot."""
    if options.input_path is None and not options.registry_id and not options.universe:
        raise ValueError("augment needs --input, --roster, or --universe")
    metadata = resolve_metadata_paths(options.artifacts_root)
    cohort = resolve_cohort(options)
    check = preflight_augment(
        cohort.roster, metadata, base_snapshot_id=base_snapshot_id
    )
    if check.is_empty:
        rows = _snapshot_row_count(metadata, base_snapshot_id)
        render_output(
            [
                KeyValueRow("no_op", "True"),
                KeyValueRow("base_snapshot_id", base_snapshot_id),
                KeyValueRow("delta_row_count", "0"),
                KeyValueRow("total_row_count", str(rows)),
                KeyValueRow("requested_cik_count", str(check.requested_count)),
                KeyValueRow("already_present_count", str(check.already_present_count)),
                KeyValueRow("refetched_ciks", ""),
                ProseRow(
                    "every requested CIK is already present in the base "
                    "snapshot; nothing fetched and nothing published"
                ),
            ],
            title="Augment (No-op)",
        )
        return 0

    progress = AugmentProgress(f"augment {base_snapshot_id[:8]}")
    metadata = resolve_metadata_paths(options.artifacts_root)
    http_client = client or build_client()
    try:
        with RunLock(
            metadata.snapshot_lock_path(base_snapshot_id),
            stale_lock_confirmed=False,
        ):
            if options.registry_id:
                result = _augment_from_registry(
                    options,
                    base_snapshot_id=base_snapshot_id,
                    new_snapshot_id=new_snapshot_id,
                    workers=workers,
                    lineage=lineage,
                    cohort=cohort,
                    preflight=check,
                    progress=progress,
                    client=http_client,
                )
            else:
                result = augment(
                    http_client,
                    cohort.roster,
                    metadata,
                    base_snapshot_id=base_snapshot_id,
                    new_snapshot_id=new_snapshot_id,
                    chunk_size=options.chunk_size,
                    workers=workers,
                    lineage=lineage,
                    preflight=check,
                    progress=progress,
                    input_name=cohort.input_name,
                    input_fingerprint=cohort.input_fingerprint,
                )
    finally:
        progress.close()
    render_output(
        [
            KeyValueRow("no_op", "False"),
            KeyValueRow("base_snapshot_id", result.base_snapshot_id),
            KeyValueRow("new_snapshot_id", result.new_snapshot_id),
            KeyValueRow("delta_plan_id", result.report.plan_id),
            KeyValueRow("base_row_count", str(result.base_row_count)),
            KeyValueRow("delta_row_count", str(result.delta_row_count)),
            KeyValueRow("total_row_count", str(result.total_row_count)),
            KeyValueRow("requested_cik_count", str(result.requested_cik_count)),
            KeyValueRow("already_present_count", str(result.already_present_count)),
            KeyValueRow("refetched_ciks", ",".join(result.refetched_ciks)),
        ],
        title="Augment Completed",
    )
    return 0


def _snapshot_row_count(metadata, snapshot_id: str) -> int:
    """Count rows in a published snapshot through its manifest."""
    parts = read_snapshot_parts(metadata.snapshot_manifest(snapshot_id))
    if parts.layout.multipart:
        return sum(int(part["row_count"]) for part in parts.layout.manifest["parts"])
    return parts.row_count


def _augment_from_registry(
    options: PlanOptions,
    *,
    base_snapshot_id: str,
    new_snapshot_id: str = "",
    workers: int | None,
    lineage: dict[str, str] | None,
    cohort: SelectedCohort | None = None,
    preflight: object = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
    client: SubmissionsClient | None = None,
):
    metadata = resolve_metadata_paths(options.artifacts_root)
    selected = cohort or resolve_cohort(options)
    return augment_from_roster(
        client or build_client(),
        selected.roster,
        metadata,
        base_snapshot_id=base_snapshot_id,
        new_snapshot_id=new_snapshot_id,
        chunk_size=options.chunk_size,
        input_name=selected.input_name,
        input_fingerprint=selected.input_fingerprint,
        workers=workers,
        preflight=preflight,
        lineage=lineage,
        progress=progress,
    )
