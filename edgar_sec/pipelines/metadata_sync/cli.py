"""Unified command surface for the metadata sync pipeline.

The command functions are plain callables so the interactive operator and the
CLI expose identical behavior. This module is an entrypoint and is therefore
allowed to exit; library modules are not.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from edgar_sec.foundation.runtime.settings import resolve_runtime_settings
from edgar_sec.foundation.runtime.settings.runtime import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_PARTITION_COUNT,
)

from .augmentation import augment_from_manifest
from .checkpoints import discover_completed_chunks
from .manifest import read_cik_manifest
from .merger import merge_chunks, publish_snapshot
from .paths import resolve_metadata_paths, resolve_run_paths
from .planner import build_plan, derive_plan_id, load_plan, plan_chunk_ids, write_plan
from .registry import compare_sources
from .sec_client import SubmissionsClient
from .source_registry import refresh_company_tickers
from .worker import resolve_workers, run_chunk, run_partition

__all__ = [
    "RunOptions",
    "build_parser",
    "cmd_augment",
    "cmd_merge",
    "cmd_plan",
    "cmd_run",
    "cmd_sources_compare",
    "cmd_sources_refresh",
    "cmd_status",
    "main",
]


@dataclass(slots=True)
class RunOptions:
    """Effective settings for one pipeline invocation.

    ``chunk_size`` and ``partition_count`` are plan-defining, so they are
    resolved once here from the CLI override when present and the settings
    registry otherwise. Resolution happens at the options boundary rather than in
    the parser, so building a parser is pure and does not read the process
    environment.
    """

    input_path: Path
    artifacts_root: Path | None = None
    chunk_size: int = DEFAULT_CHUNK_SIZE
    partition_count: int = DEFAULT_PARTITION_COUNT
    workers: int | None = None
    plan_id: str = ""
    input_fingerprint: str = ""
    limit: int | None = None

    def effective_plan_id(self, fingerprint: str) -> str:
        """Derive the plan identifier for these options and a given fingerprint."""
        return self.plan_id or derive_plan_id(
            fingerprint, self.chunk_size, self.partition_count
        )


def _options(args: argparse.Namespace) -> RunOptions:
    settings = resolve_runtime_settings()
    return RunOptions(
        input_path=Path(args.input).resolve(),
        artifacts_root=Path(args.artifacts).resolve() if args.artifacts else None,
        chunk_size=(
            settings.default_chunk_size if args.chunk_size is None else args.chunk_size
        ),
        partition_count=(
            settings.default_partition_count
            if args.partition_count is None
            else args.partition_count
        ),
        workers=args.workers,
        limit=getattr(args, "limit", None),
    )


def _build_client() -> SubmissionsClient:
    settings = resolve_runtime_settings()
    return SubmissionsClient(settings=settings.sec)


def _emit_progress(event: dict[str, Any]) -> None:
    """Render one merge progress event to stderr.

    Merge output owns stdout, so progress goes to stderr and a non-TTY run stays
    quiet rather than emitting bar control characters into a captured log.
    """
    stage = event.get("type", "progress")
    rows = event.get("rows")
    detail = f" ({rows} rows)" if rows is not None else ""
    print(f"merge: {stage}{detail}", file=sys.stderr)


def cmd_plan(args: argparse.Namespace) -> int:
    """Generate a deterministic plan without touching the network."""
    options = _options(args)
    manifest = read_cik_manifest(options.input_path)
    if options.limit:
        manifest = replace(
            manifest,
            ciks=manifest.ciks[: options.limit],
            names=manifest.names[: options.limit],
        )
    plan = build_plan(
        manifest,
        chunk_size=options.chunk_size,
        partition_count=options.partition_count,
    )
    options.plan_id = plan["plan_id"]
    run_paths = resolve_run_paths(plan["plan_id"], options.artifacts_root)
    write_plan(plan, run_paths)
    print(
        f"plan {plan['plan_id']} written: {plan['row_count']} CIKs, "
        f"{len(plan['chunks'])} chunks, {len(plan['partitions'])} partitions"
    )
    return 0


def _load(options: RunOptions) -> tuple[dict, Any]:
    if not options.plan_id:
        manifest = read_cik_manifest(options.input_path)
        options.plan_id = options.effective_plan_id(manifest.input_fingerprint)
    run_paths = resolve_run_paths(options.plan_id, options.artifacts_root)
    return load_plan(run_paths), run_paths


def cmd_status(args: argparse.Namespace) -> int:
    """Report plan progress without refetching any source data."""
    options = _options(args)
    plan, run_paths = _load(options)
    completed = discover_completed_chunks(plan, run_paths)
    planned = plan_chunk_ids(plan)
    outstanding = [chunk_id for chunk_id in planned if chunk_id not in completed]
    payload = {
        "plan_id": plan["plan_id"],
        "input_fingerprint": plan["input_fingerprint"],
        "schema_version": plan["schema_version"],
        "planned_chunks": len(planned),
        "completed_chunks": len(completed),
        "outstanding_chunks": outstanding,
        "mergeable": not outstanding,
    }
    print(json.dumps(payload, indent=2))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Execute one chunk, one partition, or the whole plan."""
    options = _options(args)
    plan, run_paths = _load(options)
    client = _build_client()
    completed = discover_completed_chunks(plan, run_paths)
    workers = resolve_workers(options.workers)
    snapshot_id = plan["plan_id"]

    if args.partition is not None:
        results = run_partition(
            client,
            plan,
            run_paths,
            args.partition,
            snapshot_id=snapshot_id,
            workers=workers,
            completed=completed,
        )
        for result in results:
            if result.skipped_existing:
                print(f"chunk {result.chunk_id}: already complete, skipped")
            else:
                print(
                    f"chunk {result.chunk_id}: {result.row_count} rows -> {result.path}"
                )
        return 0

    if args.chunk is not None:
        targets = [args.chunk]
    else:
        targets = plan_chunk_ids(plan)
    if not targets:
        print("no chunks selected")
        return 1

    for chunk_id in targets:
        if chunk_id in completed:
            print(f"chunk {chunk_id}: already complete, skipped")
            continue
        result = run_chunk(
            client,
            plan,
            run_paths,
            chunk_id,
            snapshot_id=snapshot_id,
            workers=workers,
        )
        print(f"chunk {chunk_id}: {result.row_count} rows -> {result.path}")
    return 0


def cmd_merge(args: argparse.Namespace) -> int:
    """Validate all chunks and publish a snapshot."""
    options = _options(args)
    plan, run_paths = _load(options)
    report = merge_chunks(plan, run_paths, plan["plan_id"], progress=_emit_progress)
    manifest = publish_snapshot(report, run_paths.metadata)
    print(json.dumps(manifest, indent=2))
    return 0


def cmd_augment(args: argparse.Namespace) -> int:
    """Add only the newly requested CIKs to a published snapshot."""
    options = _options(args)
    result = augment_from_manifest(
        _build_client(),
        str(options.input_path),
        resolve_metadata_paths(options.artifacts_root),
        base_snapshot_id=args.base_snapshot_id,
        new_snapshot_id=args.new_snapshot_id,
        chunk_size=options.chunk_size,
        partition_count=options.partition_count,
        workers=options.workers or None,
    )
    print(
        json.dumps(
            {
                "base_snapshot_id": result.base_snapshot_id,
                "new_snapshot_id": result.new_snapshot_id,
                "base_row_count": result.base_row_count,
                "delta_row_count": result.delta_row_count,
                "total_row_count": result.total_row_count,
                "refetched_ciks": list(result.refetched_ciks),
            },
            indent=2,
        )
    )
    return 0


def cmd_sources_refresh(args: argparse.Namespace) -> int:
    """Fetch and publish one immutable external source snapshot."""
    metadata = resolve_metadata_paths(args.artifacts or None)
    manifest = refresh_company_tickers(metadata_paths=metadata)
    print(json.dumps(manifest, indent=2))
    return 0


def cmd_sources_compare(args: argparse.Namespace) -> int:
    """Project the curated CIK input against a published source snapshot."""
    result = compare_sources(
        curated_input_path=Path(args.input).resolve(),
        source_manifest_path=Path(args.source_manifest).resolve(),
        metadata_paths=resolve_metadata_paths(args.artifacts or None),
    )
    print(json.dumps(result, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the metadata sync argument parser."""
    parser = argparse.ArgumentParser(
        prog="metadata", description="SEC submissions metadata sync pipeline"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--input", required=True, help="CIK manifest CSV")
        sub.add_argument("--artifacts", default="", help="artifacts root override")
        sub.add_argument(
            "--chunk-size",
            type=int,
            default=None,
            help=f"CIKs per resumable chunk (default: runtime.chunk_size, {DEFAULT_CHUNK_SIZE})",
        )
        sub.add_argument(
            "--partition-count",
            type=int,
            default=None,
            help=(
                "operational partitions "
                f"(default: runtime.partition_count, {DEFAULT_PARTITION_COUNT})"
            ),
        )
        sub.add_argument(
            "--workers",
            type=int,
            default=None,
            help="worker threads; machine-derived if unset",
        )

    plan_parser = subparsers.add_parser("plan", help="generate a deterministic plan")
    add_common(plan_parser)
    plan_parser.add_argument("--limit", type=int, default=None)
    plan_parser.set_defaults(func=cmd_plan)

    status_parser = subparsers.add_parser("status", help="report plan progress")
    add_common(status_parser)
    status_parser.set_defaults(func=cmd_status)

    run_parser = subparsers.add_parser("run", help="execute resumable chunks")
    add_common(run_parser)
    run_parser.add_argument("--chunk", type=int, default=None)
    run_parser.add_argument("--partition", type=int, default=None)
    run_parser.set_defaults(func=cmd_run)

    merge_parser = subparsers.add_parser("merge", help="publish a snapshot")
    add_common(merge_parser)
    merge_parser.set_defaults(func=cmd_merge)

    augment_parser = subparsers.add_parser(
        "augment", help="add new CIKs to a published snapshot"
    )
    add_common(augment_parser)
    augment_parser.add_argument("--base-snapshot-id", required=True)
    augment_parser.add_argument("--new-snapshot-id", required=True)
    augment_parser.set_defaults(func=cmd_augment)

    sources_parser = subparsers.add_parser(
        "sources", help="external source snapshot and curated-input projection"
    )
    sources_sub = sources_parser.add_subparsers(dest="source_command", required=True)

    refresh_parser = sources_sub.add_parser(
        "refresh", help="publish an immutable external source snapshot"
    )
    refresh_parser.add_argument(
        "--artifacts", default="", help="artifacts root override"
    )
    refresh_parser.set_defaults(func=cmd_sources_refresh)

    compare_parser = sources_sub.add_parser(
        "compare", help="project the curated CIK input against a source snapshot"
    )
    compare_parser.add_argument("--input", required=True, help="CIK manifest CSV")
    compare_parser.add_argument(
        "--source-manifest", required=True, help="published source manifest.json"
    )
    compare_parser.add_argument(
        "--artifacts", default="", help="artifacts root override"
    )
    compare_parser.set_defaults(func=cmd_sources_compare)

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
