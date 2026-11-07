"""Plan chunk execution command."""

from __future__ import annotations

from edgar_sec.foundation.runtime.render import KeyValueRow, render_output
from edgar_sec.pipelines.metadata_sync.checkpoints import (
    discover_completed_chunks,
)
from edgar_sec.pipelines.metadata_sync.options import RunOptions
from edgar_sec.pipelines.metadata_sync.planner import FingerprintIndex, load_plan
from edgar_sec.pipelines.metadata_sync.progress import progress_renderer
from edgar_sec.pipelines.metadata_sync.run_lock import RunLock
from edgar_sec.pipelines.metadata_sync.sec_client import (
    BulkSubmissionsClient,
    SubmissionsClient,
)
from edgar_sec.pipelines.metadata_sync.snapshot import resolve_snapshot_parts
from edgar_sec.pipelines.metadata_sync.worker import (
    CarryProvider,
    CarryReport,
    resolve_workers,
    run_chunk_ids,
    stage_carried_rows,
)

from .client import build_bulk_client, build_bulk_client_from_store, build_client


def cmd_run(
    options: RunOptions,
    *,
    client: SubmissionsClient | BulkSubmissionsClient | None = None,
) -> int:
    """Execute the chunks this invocation owns."""
    run_paths = options.run_paths()
    plan = load_plan(run_paths)
    fingerprints = None
    if plan.is_archive_plan:
        fingerprints = FingerprintIndex(run_paths.fingerprints_file)
        if client is None:
            metadata = getattr(run_paths, "metadata", None)
            if metadata is None:
                raise ValueError("archive plans execute from the artifacts tree")
            client = build_bulk_client_from_store(
                metadata.bulk_archives_root,
                plan.archive_source_id,
                plan.archive_sha256,
            )
    elif client is None and options.bulk:
        client = build_bulk_client(run_paths.metadata.bulk_archives_root)
    targets = list(options.chunk_ids) or plan.chunk_ids()
    if not targets:
        raise ValueError("no chunks selected")
    snapshot_id = options.effective_snapshot_id(plan)
    carry_report: CarryReport | None = None
    carry = None
    if options.carry_from_snapshot:
        if fingerprints is None:
            raise ValueError("--carry-from requires an archive plan")
        metadata = getattr(run_paths, "metadata", None)
        if metadata is None:
            raise ValueError("carry-forward executes from the artifacts tree")
        prior = resolve_snapshot_parts(metadata, options.carry_from_snapshot)
        carry_report = stage_carried_rows(
            plan,
            run_paths,
            prior_part_paths=prior.paths,
            fingerprints_path=run_paths.fingerprints_file,
            snapshot_id=snapshot_id,
        )
        carry = CarryProvider(carry_report.staging_dir)
    completed = discover_completed_chunks(plan, run_paths)
    outstanding = sum(
        plan.chunk_length(chunk_id) for chunk_id in targets if chunk_id not in completed
    )
    progress, bar = progress_renderer(
        "fetch", outstanding, desc=f"plan {plan.plan_id[:8]}"
    )
    try:
        with RunLock(
            run_paths.lock_path(),
            stale_lock_confirmed=options.stale_lock_confirmed,
        ):
            results = run_chunk_ids(
                client or build_client(),
                plan,
                run_paths,
                targets,
                snapshot_id=snapshot_id,
                workers=resolve_workers(options.workers),
                completed=completed,
                progress=progress,
                fingerprints=fingerprints,
                carry=carry,
            )
    finally:
        if bar is not None:
            bar.close()
    written = sum(1 for r in results if not r.skipped_existing)
    written_rows = sum(r.row_count for r in results if not r.skipped_existing)
    summary_rows = [
        KeyValueRow("plan_id", plan.plan_id),
        KeyValueRow("total_chunks", str(len(results))),
        KeyValueRow("written", str(written)),
        KeyValueRow("skipped", str(len(results) - written)),
        KeyValueRow("total_rows", str(written_rows)),
    ]
    if carry_report is not None:
        carried_here = sum(
            carry_report.carried_by_chunk.get(r.chunk_id, 0)
            for r in results
            if not r.skipped_existing
        )
        summary_rows.append(KeyValueRow("carried_rows", str(carried_here)))
        summary_rows.append(
            KeyValueRow("normalized_rows", str(written_rows - carried_here))
        )
        summary_rows.append(
            KeyValueRow("carry_from_snapshot", options.carry_from_snapshot)
        )
    if isinstance(client, BulkSubmissionsClient):
        summary_rows.append(KeyValueRow("source", "submissions bulk archive"))
        summary_rows.append(
            KeyValueRow("bulk_archive_sha256", client.archive.archive_sha256)
        )
    render_output(
        summary_rows,
        title=f"Run Summary ({plan.plan_id[:8]})",
    )
    return 0
