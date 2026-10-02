"""Unified command surface for the metadata sync pipeline.

The command functions are plain callables over one typed options model, so the
interactive operator and the CLI are the same code path rather than two shapes
that must be kept in agreement. This module is an entrypoint and is therefore
allowed to exit; library modules are not.

The command set is the whole lifecycle: refresh an external source, compare it
against a curated input, plan a full or augmented run, execute it here or on
another machine, bring the results back, merge, and publish.
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
from .augmentation import augment_from_manifest, preflight_augment
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
from .sec_client import SubmissionsClient
from .snapshot import read_snapshot_parts
from .source_registry import refresh_company_tickers
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
    """Build the live submissions client, cached against the shared response store.

    The cache root and its TTL come from the settings registry, not from a local
    constant and not from ``resolve_paths()``. The registry is the declared
    source for both, and its ``cache.root`` default is the directory the store
    already lives in. ``resolve_paths()`` computes a *different* directory from a
    *different* environment variable -- a divergence the parity inventory records
    as "root-setting env names are inconsistent" -- so reading it here would
    silently open a second, empty store next to the populated one.

    With the store wired, a repeated fetch, a resumed chunk, or a re-plan that
    re-covers CIKs already seen serves from disk and consumes no request-budget.
    The failure ledger rides along in the same file, so a URL already known bad
    is skipped without a request.
    """
    settings = resolve_runtime_settings()
    return SubmissionsClient(
        settings=settings.sec,
        cache_dir=settings.cache_root,
        json_ttl_s=settings.json_ttl_s,
    )


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2))


def cmd_refresh(artifacts_root: Path | None = None) -> int:
    """Fetch and publish one immutable external source snapshot."""
    metadata = resolve_metadata_paths(artifacts_root)
    _emit(refresh_company_tickers(metadata_paths=metadata))
    return 0


def cmd_compare(options: PlanOptions, *, source_manifest: Path) -> int:
    """Project the curated CIK input against a published source snapshot.

    A pure projection over two immutable inputs, so it needs no network and is
    reproducible: the same curated file and the same source snapshot always
    publish the same registry identity and the same roster.
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
    """Generate a deterministic plan without touching the network.

    Emits the immutable bundle: the roster dataset, the execution manifest, and
    the input diagnostics. A registry roster and a curated CSV converge here, so
    the rest of the lifecycle cannot tell them apart.
    """
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

    A single host names no chunks and runs everything outstanding. A worker names
    its assignment's chunks and runs only those. Both take the same path, so
    there is no separate worker mode that has to be kept correct.
    """
    run_paths = options.run_paths()
    plan = load_plan(run_paths)
    targets = list(options.chunk_ids) or plan.chunk_ids()
    if not targets:
        raise ValueError("no chunks selected")
    completed = discover_completed_chunks(plan, run_paths)
    # The final chunk of a roster is usually partial, so the total has to be the
    # sum of actual chunk lengths rather than chunk_size per chunk. Summing
    # chunk_size overstated the cohort and skewed the bar's ETA.
    outstanding = sum(
        plan.chunk_length(chunk_id) for chunk_id in targets if chunk_id not in completed
    )
    progress, bar = progress_renderer(
        "fetch", outstanding, desc=f"plan {plan.plan_id[:8]}"
    )
    try:
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
    """Add only the newly requested CIKs to a published snapshot.

    The delta plan is bound to its base snapshot, so the same requested list
    against two different bases is two different plans. Only the delta is
    fetched; the base is merged forward untouched.

    An empty ``new_snapshot_id`` publishes under the derived delta plan id, so
    the command needs no hand-typed identity and is idempotent across reruns.

    The cohort is reduced against the base before the submissions client is
    built. A request the base already satisfies is the ordinary case for a
    stale seed, and answering it costs no client, no SEC request, and no
    published delta plan; it exits 0 with ``no_op`` set, because nothing failed.
    """
    if options.input_path is None and not options.registry_id:
        raise ValueError("augment needs --input or --roster")
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
    try:
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
            result = augment_from_manifest(
                _build_client(),
                str(options.input_path),
                metadata,
                base_snapshot_id=base_snapshot_id,
                new_snapshot_id=new_snapshot_id,
                chunk_size=options.chunk_size,
                workers=workers,
                lineage=lineage,
                preflight=check,
                progress=progress,
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
    from .augmentation import augment_from_roster

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

    The bundle is byte-identical for every worker; only the assignment beside it
    differs. That is what makes the distribution checkable rather than
    negotiated: each worker can verify it holds the plan the coordinator planned.
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

    The worker holds a copied bundle and its own assignment. It learns nothing
    from the coordinator while running, and it cannot widen its own scope: the
    chunk list comes from the assignment, whose identity is re-derived on load.
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

    This is the trust boundary. Files arrive from another machine, so the plan
    identity, the assignment identity, the per-file digest, the canonical schema,
    the row count, and the chunk's CIK coverage are all checked before a file is
    placed.
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
    """Attach either an explicit plan reference or a cohort reference.

    A worker holding only a copied bundle names its plan outright. A single host
    may instead name the cohort it planned from, and the plan id is re-derived
    from that cohort and the effective chunk layout, which is what makes replanning
    idempotent and a changed chunk layout fail loudly rather than silently reuse
    another plan's checkpoints.
    """
    group = sub.add_mutually_exclusive_group()
    group.add_argument("--plan-id", default="", help="plan identifier to operate on")
    group.add_argument("--bundle", default="", help="copied plan bundle directory")
    group.add_argument("--input", default="", help="CIK manifest CSV to re-derive from")
    group.add_argument("--roster", default="", help="effective CIK roster id")


def _add_cohort_source(sub: argparse.ArgumentParser, *, with_limit: bool) -> None:
    """Attach the cohort reference a plan is created over."""
    group = sub.add_mutually_exclusive_group(required=True)
    group.add_argument("--input", default="", help="CIK manifest CSV")
    group.add_argument(
        "--roster", default="", help="effective CIK roster id from 'sources compare'"
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
        artifacts_root=args.artifacts or None,
        chunk_size=args.chunk_size,
        limit=getattr(args, "limit", None),
    )


def _run_options(args: argparse.Namespace) -> RunOptions:
    return run_options(
        plan_id=getattr(args, "plan_id", "") or "",
        input_path=getattr(args, "input", "") or None,
        registry_id=getattr(args, "roster", "") or "",
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
    refresh_parser.set_defaults(
        func=lambda args: cmd_refresh(Path(args.artifacts) if args.artifacts else None)
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

    return parser


def _augment_from_args(args: argparse.Namespace) -> int:
    options, lineage = augment_options(
        input_path=args.input or None,
        registry_id=args.roster,
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
