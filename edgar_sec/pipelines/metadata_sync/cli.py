"""Unified command surface for the metadata sync pipeline.

Every command is a plain callable over one typed options model, so the operator
and the CLI are one code path.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from edgar_sec.foundation.runtime.settings import resolve_runtime_settings

from .assignment import AssignmentError
from .augmentation import augment, augment_from_roster, preflight_augment
from .checkpoints import discover_completed_chunks
from .distribution import (
    adopt_chunks,
    build_worker_receipt,
    coordinator_run_paths,
    export_bundle,
    load_returned_plan,
    select_assignment,
    write_receipt,
)
from .family_index import ensure_family_index
from .merger import merge_chunks, publish_snapshot
from .options import (
    PlanOptions,
    RunOptions,
    SelectedCohort,
    augment_options,
    plan_options,
    resolve_cohort,
    run_options,
)
from .paths import resolve_metadata_paths, resolve_run_paths
from .planner import load_plan, write_plan
from .progress import MERGE_PROGRESS_STAGES, AugmentProgress, progress_renderer
from .registry import compare_sources
from .roster import RosterError
from .run_lock import RunLock
from .sec_client import SubmissionsClient
from .snapshot import read_snapshot_parts
from .source_registry import (
    SOURCE_NAME,
    SOURCE_UNIVERSE_NAME,
    refresh_cik_lookup_universe,
    refresh_company_tickers,
)
from .worker import resolve_workers, run_chunk_ids

__all__ = [
    "build_parser",
    "cmd_augment",
    "cmd_compare",
    "cmd_export",
    "cmd_import",
    "cmd_merge",
    "cmd_plan",
    "cmd_refresh",
    "cmd_run",
    "cmd_status",
    "cmd_worker",
    "main",
]


def _build_client() -> SubmissionsClient:
    """Build the submissions client against the shared response store.

    The settings registry owns the cache root; ``resolve_paths()`` would open a
    second, empty store.
    """
    settings = resolve_runtime_settings()
    return SubmissionsClient(
        settings=settings.sec,
        cache_dir=settings.cache_root,
        ttl_s=settings.ttl_s,
    )


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2))


def cmd_refresh(
    artifacts_root: Path | None = None, *, source: str = SOURCE_NAME
) -> int:
    """Fetch and publish one immutable external source snapshot."""
    metadata = resolve_metadata_paths(artifacts_root)
    if source == SOURCE_UNIVERSE_NAME:
        _emit(refresh_cik_lookup_universe(metadata_paths=metadata))
    else:
        _emit(refresh_company_tickers(metadata_paths=metadata))
    return 0


def cmd_family_index(artifacts_root: Path | None = None) -> int:
    """Assign a company family to every registrant of the published universe.

    Policy-scope planning needs this artifact, and builds it on demand. Running it
    here makes the cost and its inputs visible instead of hiding them inside a plan.
    """
    metadata = resolve_metadata_paths(artifacts_root)
    artifact = ensure_family_index(metadata)
    _emit(
        {
            "family_index_id": artifact.family_index_id,
            "assignment": str(artifact.assignment_path),
            "manifest": str(artifact.manifest_path),
            **_family_index_summary(artifact.manifest_path),
        }
    )
    return 0


def _family_index_summary(manifest_path: Path) -> dict[str, Any]:
    """The counts an operator needs to judge the artifact, read back from its manifest."""
    recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        key: recorded[key]
        for key in (
            "schema_version",
            "roster_id",
            "dataset_sha256",
            "assignment_sha256",
            "rules_fingerprint",
            "registrants",
            "entity_families",
            "spv_families",
            "singletons",
            "spv_registrants",
            "unresolved_sponsors",
        )
    }


def cmd_compare(options: PlanOptions, *, source_manifest: Path) -> int:
    """Project the curated CIK input against a published source snapshot.
    Two immutable inputs, so the same pair always yields the same identity.
    """
    if options.input_path is None:
        raise ValueError("sources compare needs --input")
    _emit(
        compare_sources(
            curated_input_path=options.input_path,
            source_manifest_path=source_manifest,
            metadata_paths=resolve_metadata_paths(options.artifacts_root),
        )
    )
    return 0


def cmd_plan(options: PlanOptions) -> int:
    """Generate a deterministic plan without touching the network."""
    cohort = resolve_cohort(options)
    from .planner import build_plan

    plan = build_plan(
        cohort.roster,
        chunk_size=options.chunk_size,
        input_name=cohort.input_name,
        input_fingerprint=cohort.input_fingerprint,
        selected_limit=options.limit,
        registry_id=options.registry_id,
    )
    run_paths = resolve_run_paths(plan.plan_id, options.artifacts_root)
    write_plan(plan, run_paths)
    _emit(
        {
            "plan_id": plan.plan_id,
            "roster_id": plan.roster.roster_id,
            "row_count": plan.row_count,
            "chunk_size": plan.chunk_size,
            "chunk_count": plan.chunk_count,
            "plan_dir": str(run_paths.plan_bundle),
        }
    )
    return 0


def cmd_status(options: RunOptions) -> int:
    """Report plan progress without refetching any source data."""
    run_paths = options.run_paths()
    plan = load_plan(run_paths)
    completed = discover_completed_chunks(plan, run_paths)
    planned = plan.chunk_ids()
    outstanding = [chunk_id for chunk_id in planned if chunk_id not in completed]
    _emit(
        {
            "plan_id": plan.plan_id,
            "roster_id": plan.roster.roster_id,
            "row_count": plan.row_count,
            "input_fingerprint": plan.input_fingerprint,
            "schema_version": plan.schema_version,
            "planned_chunks": len(planned),
            "completed_chunks": len(completed),
            "outstanding_chunks": outstanding,
            "mergeable": not outstanding,
        }
    )
    return 0


def cmd_run(options: RunOptions, *, client: SubmissionsClient | None = None) -> int:
    """Execute the chunks this invocation owns.
    A single host runs everything outstanding; a worker only its assignment's.
    """
    run_paths = options.run_paths()
    plan = load_plan(run_paths)
    targets = list(options.chunk_ids) or plan.chunk_ids()
    if not targets:
        raise ValueError("no chunks selected")
    completed = discover_completed_chunks(plan, run_paths)
    # The final chunk is usually partial, so the total must be the sum of actual
    # chunk lengths; summing chunk_size overstates the cohort.
    outstanding = sum(
        plan.chunk_length(chunk_id) for chunk_id in targets if chunk_id not in completed
    )
    progress, bar = progress_renderer(
        "fetch", outstanding, desc=f"plan {plan.plan_id[:8]}"
    )
    try:
        with RunLock(run_paths.lock_path(), stale_lock_confirmed=False):
            results = run_chunk_ids(
                client or _build_client(),
                plan,
                run_paths,
                targets,
                snapshot_id=options.effective_snapshot_id(plan),
                workers=resolve_workers(options.workers),
                completed=completed,
                progress=progress,
            )
    finally:
        if bar is not None:
            bar.close()
    for result in results:
        if result.skipped_existing:
            _emit({"chunk_id": result.chunk_id, "status": "already_complete"})
        else:
            _emit(
                {
                    "chunk_id": result.chunk_id,
                    "status": "written",
                    "row_count": result.row_count,
                    "path": result.path,
                }
            )
    return 0


def cmd_merge(options: RunOptions, *, lineage: dict[str, str] | None = None) -> int:
    """Validate every chunk and publish a snapshot."""
    run_paths = options.run_paths()
    plan = load_plan(run_paths)
    progress, bar = progress_renderer(
        "merge", MERGE_PROGRESS_STAGES, desc=f"merge {plan.plan_id[:8]}"
    )
    try:
        with RunLock(run_paths.lock_path(), stale_lock_confirmed=False):
            report = merge_chunks(
                plan,
                run_paths,
                options.effective_snapshot_id(plan),
                lineage=lineage,
                progress=progress,
            )
    finally:
        if bar is not None:
            bar.close()
    _emit(publish_snapshot(report, run_paths.metadata))
    return 0


def cmd_augment(
    options: PlanOptions,
    *,
    base_snapshot_id: str,
    new_snapshot_id: str = "",
    workers: int | None = None,
    lineage: dict[str, str] | None = None,
) -> int:
    """Add only the newly requested CIKs to a published snapshot; the delta plan is
    bound to its base, and an empty ``new_snapshot_id`` makes a rerun idempotent.
    """
    if options.input_path is None and not options.registry_id and not options.universe:
        raise ValueError("augment needs --input, --roster, or --universe")
    metadata = resolve_metadata_paths(options.artifacts_root)
    cohort = resolve_cohort(options)
    check = preflight_augment(
        cohort.roster, metadata, base_snapshot_id=base_snapshot_id
    )
    if check.is_empty:
        rows = _snapshot_row_count(metadata, base_snapshot_id)
        _emit(
            {
                "no_op": True,
                "base_snapshot_id": base_snapshot_id,
                "new_snapshot_id": "",
                "base_row_count": rows,
                "delta_row_count": 0,
                "total_row_count": rows,
                "requested_cik_count": check.requested_count,
                "already_present_count": check.already_present_count,
                "refetched_ciks": [],
                "message": (
                    "every requested CIK is already present in the base snapshot;"
                    " nothing fetched and nothing published"
                ),
            }
        )
        return 0

    progress = AugmentProgress(f"augment {base_snapshot_id[:8]}")
    metadata = resolve_metadata_paths(options.artifacts_root)
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
                )
            else:
                result = augment(
                    _build_client(),
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
    _emit(
        {
            "no_op": False,
            "base_snapshot_id": result.base_snapshot_id,
            "new_snapshot_id": result.new_snapshot_id,
            "delta_plan_id": result.report.plan_id,
            "delta_roster_id": result.report.delta_roster_id,
            "base_row_count": result.base_row_count,
            "delta_row_count": result.delta_row_count,
            "total_row_count": result.total_row_count,
            "requested_cik_count": result.requested_cik_count,
            "already_present_count": result.already_present_count,
            "refetched_ciks": list(result.refetched_ciks),
        }
    )
    return 0


def _snapshot_row_count(metadata, snapshot_id: str) -> int:
    """Rows in a published snapshot, read through its manifest's part list."""
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
):
    metadata = resolve_metadata_paths(options.artifacts_root)
    selected = cohort or resolve_cohort(options)
    return augment_from_roster(
        _build_client(),
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


def cmd_export(options: RunOptions, *, worker_count: int, destination: Path) -> int:
    """Copy the immutable plan bundle out, one directory per worker.
    Only the assignment beside it differs, so each worker can verify its bundle.
    """
    plan = load_plan(coordinator_run_paths(options))
    _emit(
        {
            "plan_id": plan.plan_id,
            "roster_id": plan.roster.roster_id,
            "row_count": plan.row_count,
            "chunk_count": plan.chunk_count,
            "destination": str(destination),
            "workers": export_bundle(
                plan,
                coordinator_run_paths(options),
                worker_count=worker_count,
                destination=destination,
            ),
        }
    )
    return 0


def cmd_worker(options: RunOptions, *, client: SubmissionsClient | None = None) -> int:
    """Run this worker's assigned chunks and emit a receipt.

    The chunk list comes from an assignment re-derived on load, so a worker cannot
    widen its own scope.
    """
    run_paths = options.run_paths()
    plan = load_plan(run_paths)
    assignment = select_assignment(options, run_paths)
    if assignment.plan_id != plan.plan_id:
        raise AssignmentError(
            f"assignment belongs to plan {assignment.plan_id!r}, "
            f"this bundle is plan {plan.plan_id!r}"
        )
    results = run_chunk_ids(
        client or _build_client(),
        plan,
        run_paths,
        list(assignment.chunk_ids),
        snapshot_id=options.effective_snapshot_id(plan),
        workers=resolve_workers(options.workers),
    )
    receipt = build_worker_receipt(plan, assignment, results, run_paths.bundle_root)
    _emit(
        {
            "plan_id": receipt.plan_id,
            "assignment_id": receipt.assignment_id,
            "worker_id": receipt.worker_id,
            "chunks": receipt.chunk_ids(),
            "row_count": receipt.row_count,
            "receipt_path": str(write_receipt(receipt, run_paths.receipt_file)),
        }
    )
    return 0


def cmd_import(options: RunOptions, *, source: Path) -> int:
    """Verify a worker's returned chunks and adopt them for the merge.
    Every identity in the receipt is checked before a file is placed.
    """
    run_paths = coordinator_run_paths(options)
    plan, receipt, assignment = load_returned_plan(run_paths, source)
    adopted, ignored = adopt_chunks(plan, run_paths, source, receipt, assignment)
    _emit(
        {
            "plan_id": plan.plan_id,
            "worker_id": receipt.worker_id,
            "assignment_id": assignment.assignment_id,
            "imported_chunks": adopted,
            "already_present": ignored,
        }
    )
    return 0


# ------------------------------------------------------------------- argparse


def _add_common(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--artifacts", default="", help="artifacts root override")
    sub.add_argument(
        "--chunk-size",
        type=int,
        default=None,
        help="CIKs per resumable chunk; defaults to runtime.chunk_size",
    )
    sub.add_argument(
        "--workers",
        type=int,
        default=None,
        help="worker threads; machine-derived if unset",
    )


def _add_plan_reference(sub: argparse.ArgumentParser) -> None:
    """Attach an explicit plan reference or a cohort reference; a cohort's plan id is
    re-derived, so replanning is idempotent and a changed chunk layout fails loudly.
    """
    group = sub.add_mutually_exclusive_group()
    group.add_argument("--plan-id", default="", help="plan identifier to operate on")
    group.add_argument("--bundle", default="", help="copied plan bundle directory")
    group.add_argument("--input", default="", help="CIK manifest CSV to re-derive from")
    group.add_argument("--roster", default="", help="effective CIK roster id")
    group.add_argument(
        "--universe",
        action="store_true",
        help="full SEC registrant index to re-derive from",
    )


def _add_cohort_source(sub: argparse.ArgumentParser, *, with_limit: bool) -> None:
    """Attach the cohort reference a plan is created over."""
    group = sub.add_mutually_exclusive_group(required=True)
    group.add_argument("--input", default="", help="CIK manifest CSV")
    group.add_argument(
        "--roster", default="", help="effective CIK roster id from 'sources compare'"
    )
    group.add_argument(
        "--universe", action="store_true", help="full SEC registrant index"
    )
    if with_limit:
        sub.add_argument("--limit", type=int, default=None)


def _add_chunk_selection(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--chunks", default="", help="chunk ids or ranges, e.g. '0-3,7'")
    sub.add_argument("--chunk", type=int, default=None, help="a single chunk id")


def _plan_options(args: argparse.Namespace) -> PlanOptions:
    return plan_options(
        input_path=args.input or None,
        registry_id=args.roster,
        universe=args.universe,
        artifacts_root=args.artifacts or None,
        chunk_size=args.chunk_size,
        limit=getattr(args, "limit", None),
    )


def _run_options(args: argparse.Namespace) -> RunOptions:
    return run_options(
        plan_id=getattr(args, "plan_id", "") or "",
        input_path=getattr(args, "input", "") or None,
        registry_id=getattr(args, "roster", "") or "",
        universe=getattr(args, "universe", False),
        chunk_size=args.chunk_size,
        limit=getattr(args, "limit", None),
        artifacts_root=args.artifacts or None,
        bundle_root=getattr(args, "bundle", "") or None,
        worker_id=getattr(args, "worker", "") or "",
        chunk_ids=_chunk_selection(args),
        workers=args.workers,
    )


def _chunk_selection(args: argparse.Namespace) -> tuple[int, ...]:
    selected: list[int] = []
    spec = getattr(args, "chunks", "")
    if spec:
        from edgar_sec.foundation.runtime.partitions import parse_id_selection

        selected.extend(parse_id_selection(spec))
    single = getattr(args, "chunk", None)
    if single is not None:
        selected.append(single)
    return tuple(sorted(set(selected)))


def _require(value: str, flag: str) -> str:
    if not value:
        raise ValueError(f"{flag} is required")
    return value


def build_parser() -> argparse.ArgumentParser:
    """Build the metadata sync argument parser."""
    parser = argparse.ArgumentParser(
        prog="metadata", description="SEC submissions metadata sync pipeline"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="generate a deterministic plan")
    _add_cohort_source(plan_parser, with_limit=True)
    _add_common(plan_parser)
    plan_parser.set_defaults(func=lambda args: cmd_plan(_plan_options(args)))

    status_parser = subparsers.add_parser("status", help="report plan progress")
    _add_plan_reference(status_parser)
    _add_common(status_parser)
    status_parser.set_defaults(func=lambda args: cmd_status(_run_options(args)))

    run_parser = subparsers.add_parser("run", help="execute resumable chunks")
    _add_plan_reference(run_parser)
    _add_common(run_parser)
    _add_chunk_selection(run_parser)
    run_parser.set_defaults(func=lambda args: cmd_run(_run_options(args)))

    merge_parser = subparsers.add_parser("merge", help="publish a snapshot")
    _add_plan_reference(merge_parser)
    _add_common(merge_parser)
    merge_parser.set_defaults(func=lambda args: cmd_merge(_run_options(args)))

    worker_parser = subparsers.add_parser(
        "worker", help="run this worker's assigned chunks from a copied bundle"
    )
    _add_plan_reference(worker_parser)
    _add_common(worker_parser)
    worker_parser.add_argument(
        "--worker", default="", help="worker id, when the bundle carries several"
    )
    worker_parser.set_defaults(func=lambda args: cmd_worker(_run_options(args)))

    export_parser = subparsers.add_parser(
        "export", help="copy the plan bundle out, one directory per worker"
    )
    _add_plan_reference(export_parser)
    _add_common(export_parser)
    export_parser.add_argument(
        "--worker-count", type=int, required=True, help="disjoint assignments to emit"
    )
    export_parser.add_argument("--destination", required=True, help="output directory")
    export_parser.set_defaults(
        func=lambda args: cmd_export(
            _run_options(args),
            worker_count=args.worker_count,
            destination=Path(_require(args.destination, "--destination")).resolve(),
        )
    )

    import_parser = subparsers.add_parser(
        "import", help="verify a worker's returned chunks and adopt them"
    )
    _add_plan_reference(import_parser)
    _add_common(import_parser)
    import_parser.add_argument(
        "--source", required=True, help="directory holding the returned bundle"
    )
    import_parser.set_defaults(
        func=lambda args: cmd_import(
            _run_options(args),
            source=Path(_require(args.source, "--source")).resolve(),
        )
    )

    augment_parser = subparsers.add_parser(
        "augment", help="add new CIKs to a published snapshot"
    )
    _add_cohort_source(augment_parser, with_limit=False)
    _add_common(augment_parser)
    augment_parser.add_argument("--base-snapshot-id", required=True)
    augment_parser.add_argument(
        "--new-snapshot-id",
        default="",
        help=(
            "snapshot id to publish under; defaults to the derived delta plan id, "
            "which is content-addressed over the base snapshot and delta cohort"
        ),
    )
    augment_parser.set_defaults(func=lambda args: _augment_from_args(args))

    sources_parser = subparsers.add_parser(
        "sources", help="external source snapshot and curated-input projection"
    )
    sources_sub = sources_parser.add_subparsers(dest="source_command", required=True)

    refresh_parser = sources_sub.add_parser(
        "refresh", help="publish an immutable external source snapshot"
    )
    refresh_parser.add_argument("--artifacts", default="")
    refresh_parser.add_argument(
        "--source",
        default=SOURCE_NAME,
        choices=[SOURCE_NAME, SOURCE_UNIVERSE_NAME],
        help="which external source to refresh",
    )
    refresh_parser.set_defaults(
        func=lambda args: cmd_refresh(
            Path(args.artifacts) if args.artifacts else None, source=args.source
        )
    )

    compare_parser = sources_sub.add_parser(
        "compare", help="project the curated CIK input against a source snapshot"
    )
    compare_parser.add_argument(
        "--input", required=True, help="curated CIK manifest CSV"
    )
    compare_parser.add_argument(
        "--source-manifest", required=True, help="published source manifest.json"
    )
    compare_parser.add_argument("--artifacts", default="")
    compare_parser.set_defaults(
        func=lambda args: cmd_compare(
            plan_options(
                input_path=args.input,
                artifacts_root=args.artifacts or None,
            ),
            source_manifest=Path(args.source_manifest).resolve(),
        )
    )

    family_index_parser = subparsers.add_parser(
        "family-index",
        help="assign a company family to every registrant of the published universe",
    )
    family_index_parser.add_argument("--artifacts", default="")
    family_index_parser.set_defaults(
        func=lambda args: cmd_family_index(
            Path(args.artifacts) if args.artifacts else None
        )
    )

    return parser


def _augment_from_args(args: argparse.Namespace) -> int:
    options, lineage = augment_options(
        input_path=args.input or None,
        registry_id=args.roster,
        universe=args.universe,
        artifacts_root=args.artifacts or None,
        chunk_size=args.chunk_size,
        base_snapshot_id=args.base_snapshot_id,
        new_snapshot_id=args.new_snapshot_id,
        workers=args.workers,
    )
    return cmd_augment(
        options,
        base_snapshot_id=args.base_snapshot_id,
        new_snapshot_id=args.new_snapshot_id,
        workers=args.workers,
        lineage=lineage,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except (
        AssignmentError,
        FileNotFoundError,
        RosterError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
