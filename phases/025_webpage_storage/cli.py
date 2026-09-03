"""Canonical Phase 2.5 command surface."""

from __future__ import annotations

import argparse
import importlib
import sys
from contextlib import suppress
from pathlib import Path

from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm

from defs.runtime.cli import print_json
from defs.runtime.paths import resolve_paths
from defs.runtime.progress import make_tqdm_callback
from defs.runtime.resources import derive_resources
from defs.sql import Select, SqlDialect, Table, col, make_sql_executor

from .core import pipeline
from .core.partition_merger import merge_partition
from .core.schemas import (
    ACQUISITION_FAILURES_TABLE,
    COMMITTED_CHUNKS_TABLE,
    DOCUMENT_BLOBS_TABLE,
    FILING_OCCURRENCES_TABLE,
)


def _add_plan_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--plan-dir",
        default=None,
        help="Phase 02 finalized target plan directory (defaults to latest discovered target plan)",
    )
    parser.add_argument(
        "--output-dir", default=None, help="published partition database directory"
    )


def _resolve_plan_dir(plan_dir: str | None) -> str:
    if plan_dir:
        return plan_dir
    with suppress(ImportError, OSError, ValueError):
        discovery = importlib.import_module(
            "phases.02_filing_extraction.core.discovery"
        )
        plans = discovery.discover_plans()
        if plans:
            return plans[0]["path"]
    raise ValueError(
        "No Phase 02 target plan found. Run Phase 02 target plan or specify --plan-dir."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="phases.025_webpage_storage.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    preview_parser = subparsers.add_parser(
        "preview", help="enumerate planned acquisitions from a Phase 02 target plan"
    )
    _add_plan_args(preview_parser)
    preview_parser.add_argument("--partition-count", type=int, default=1)
    preview_parser.add_argument("--chunk-size", type=int, default=None)

    run_parser = subparsers.add_parser("run", help="acquire and store one partition")
    _add_plan_args(run_parser)
    run_parser.add_argument(
        "--mode", choices=("fixture", "production"), default="fixture"
    )
    run_parser.add_argument("--partition-id", type=int, default=1)
    run_parser.add_argument("--partition-count", type=int, default=1)
    run_parser.add_argument("--chunk-size", type=int, default=None)
    run_parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="worker threads (defaults to system CPU budget)",
    )
    run_parser.add_argument(
        "--no-normalize",
        action="store_true",
        help="store raw payloads without running the normalization pipeline",
    )
    run_parser.add_argument("--run-id", default="local")
    run_parser.add_argument(
        "--fixtures", default=None, help="comma-separated fixture ids for fixture mode"
    )
    run_parser.add_argument(
        "--no-progress", action="store_true", help="disable the tqdm progress bar"
    )

    merge_partition_parser = subparsers.add_parser(
        "merge-partition",
        help="merge transient worker chunks into a partition database",
    )
    merge_partition_parser.add_argument("--partition-id", type=int, required=True)
    merge_partition_parser.add_argument("--run-id", default="local")
    merge_partition_parser.add_argument("--output-dir", required=True)

    status_parser = subparsers.add_parser(
        "status", help="report partition database integrity and record counts"
    )
    status_parser.add_argument(
        "--database", required=True, help="partition database path"
    )

    fill_fixture_parser = subparsers.add_parser(
        "fill-fixture",
        help="populate an offline SQLite fixture from a target plan and live SEC client",
    )
    _add_plan_args(fill_fixture_parser)
    fill_fixture_parser.add_argument(
        "--fixture-id",
        default=None,
        help="destination fixture ID name (defaults to fix-<plan_id>)",
    )
    fill_fixture_parser.add_argument(
        "--limit", type=int, default=None, help="maximum unique documents to fetch"
    )
    fill_fixture_parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="fetch threads (defaults to machine-local runtime threads)",
    )
    fill_fixture_parser.add_argument(
        "--retry-failures",
        action="store_true",
        help="retry acquisition failures belonging to the current plan",
    )
    fill_fixture_parser.add_argument(
        "--no-progress", action="store_true", help="disable the tqdm progress bar"
    )
    return parser


def _fixture_paths(fixtures: str | None) -> list[Path] | None:
    if fixtures:
        return [
            resolve_paths().fixture(fid.strip(), dialect="sqlite").db_path
            for fid in fixtures.split(",")
            if fid.strip()
        ]
    fixtures_root = resolve_paths().fixtures_root
    if fixtures_root.is_dir():
        dbs = [
            d / "fixture.sqlite"
            for d in sorted(fixtures_root.iterdir())
            if d.is_dir() and (d / "fixture.sqlite").is_file()
        ]
        if dbs:
            return dbs
    return None


def _resolved_output(args) -> str:
    if getattr(args, "output_dir", None):
        return args.output_dir
    return str(
        resolve_paths("webpage_storage").project.manifests_root
        / "filing_documents"
        / "final"
    )


def _status(database: str) -> dict:
    path = Path(database)
    if not path.is_file():
        return {
            "database": database,
            "exists": False,
            "blobs": 0,
            "occurrences": 0,
            "failures": 0,
            "committed_chunks": 0,
        }
    executor = make_sql_executor(database, dialect=SqlDialect.SQLITE)
    try:
        blobs = executor.query(
            executor.compiler.compile(
                Select(source=Table(DOCUMENT_BLOBS_TABLE), projection=(col("doc_id"),))
            )
        )
        occurrences = executor.query(
            executor.compiler.compile(
                Select(
                    source=Table(FILING_OCCURRENCES_TABLE),
                    projection=(col("occurrence_id"),),
                )
            )
        )
        failures = executor.query(
            executor.compiler.compile(
                Select(
                    source=Table(ACQUISITION_FAILURES_TABLE),
                    projection=(col("doc_id"),),
                )
            )
        )
        chunks = executor.query(
            executor.compiler.compile(
                Select(
                    source=Table(COMMITTED_CHUNKS_TABLE),
                    projection=(col("chunk_id"),),
                )
            )
        )
        return {
            "database": database,
            "exists": True,
            "blobs": len(blobs),
            "occurrences": len(occurrences),
            "failures": len(failures),
            "committed_chunks": len(chunks),
        }
    finally:
        executor.close()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "preview":
            plan_dir = _resolve_plan_dir(getattr(args, "plan_dir", None))
            locators, occurrences, plan = pipeline.load_targets(plan_dir)
            selected = pipeline._partition_locators(
                locators,
                args.partition_id if hasattr(args, "partition_id") else 1,
                args.partition_count,
            )
            effective_chunk_size = (
                args.chunk_size
                if (args.chunk_size is not None and args.chunk_size > 0)
                else pipeline.calculate_optimal_chunk_size(len(selected), 1)
            )
            print_json(
                {
                    "locator_count": len(locators),
                    "occurrence_count": len(occurrences),
                    "plan_scope": plan.get("scope"),
                    "partition_count": args.partition_count,
                    "chunk_size": effective_chunk_size,
                }
            )
            return 0
        if args.command == "run":
            plan_dir = _resolve_plan_dir(getattr(args, "plan_dir", None))
            workers = (
                args.workers
                if args.workers is not None
                else max(1, derive_resources().workers)
            )
            http_client = None
            progress_cb = None
            pbar = None
            if not getattr(args, "no_progress", False):
                locators, _, _ = pipeline.load_targets(plan_dir)
                selected = pipeline._partition_locators(
                    locators, args.partition_id, args.partition_count
                )
                pbar = tqdm(
                    total=len(selected),
                    desc="Acquiring documents",
                    unit="doc",
                )
                progress_cb = make_tqdm_callback(pbar)

            with logging_redirect_tqdm():
                try:
                    processor = None
                    if not getattr(args, "no_normalize", False):
                        processors_mod = importlib.import_module(
                            "phases.025_webpage_storage.processors"
                        )
                        processor = processors_mod.DefaultFilingProcessor()
                    result = pipeline.run_partition(
                        plan_dir,
                        _resolved_output(args),
                        mode=args.mode,
                        fixture_paths=_fixture_paths(getattr(args, "fixtures", None)),
                        http_client=http_client,
                        run_id=args.run_id,
                        partition_id=args.partition_id,
                        partition_count=args.partition_count,
                        chunk_size=args.chunk_size,
                        workers=workers,
                        progress=progress_cb,
                        processor=processor,
                    )
                finally:
                    if pbar is not None:
                        pbar.close()

            print_json(result)
            return 0
        if args.command == "merge-partition":
            run_paths = resolve_paths("webpage_storage", args.run_id)
            chunk_dbs = sorted(run_paths.workers_root.glob("*/*/chunk-*.db"))
            if not chunk_dbs:
                chunk_dbs = sorted(run_paths.workers_root.glob("*/chunk-*.db"))
            output = Path(args.output_dir)
            output.mkdir(parents=True, exist_ok=True)
            partition_name = (
                resolve_paths()
                .dataset_manifests(
                    "webpage_storage",
                    "filing_documents",
                    f"partition-{args.partition_id:05d}",
                )
                .name
                + ".sqlite"
            )
            merge_result = merge_partition(output / partition_name, chunk_dbs)
            print_json(merge_result.to_dict())
            return 0
        if args.command == "status":
            print_json(_status(args.database))
            return 0
        if args.command == "fill-fixture":
            from .core.fixture_builder import fill_fixture

            plan_dir = _resolve_plan_dir(getattr(args, "plan_dir", None))
            fixture_id = (
                args.fixture_id if args.fixture_id else f"fix-{Path(plan_dir).name[:8]}"
            )
            workers = (
                args.workers
                if args.workers is not None
                else max(1, derive_resources().threads)
            )
            progress_cb = None
            pbar = None
            if not getattr(args, "no_progress", False):
                locators, _, _ = pipeline.load_targets(plan_dir)
                total = min(len(locators), args.limit) if args.limit else len(locators)
                pbar = tqdm(
                    total=total,
                    desc=f"Filling fixture '{fixture_id}'",
                    unit="doc",
                )
                progress_cb = make_tqdm_callback(pbar)

            with logging_redirect_tqdm():
                try:
                    result = fill_fixture(
                        plan_dir,
                        fixture_id=fixture_id,
                        limit=args.limit,
                        workers=workers,
                        retry_failures=args.retry_failures,
                        progress=progress_cb,
                    )
                finally:
                    if pbar is not None:
                        pbar.close()

            print_json(result)
            return 0
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print("error: unknown command", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
