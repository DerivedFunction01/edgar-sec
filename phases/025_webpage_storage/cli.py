"""Canonical Phase 2.5 command surface."""

from __future__ import annotations

import argparse
import importlib
import sys
from contextlib import suppress
from pathlib import Path

from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm

from defs.runtime.artifacts import get_current_snapshot_pointer
from defs.runtime.cli import print_json
from defs.runtime.paths import resolve_paths
from defs.runtime.progress import make_tqdm_callback
from defs.runtime.resources import derive_resources
from defs.sql import (
    Aggregate,
    AggregateFunction,
    Select,
    SqlDialect,
    Star,
    Table,
    make_sql_executor,
)

from .core import pipeline
from .core.partition_handoff import handoff_path, validate_handoffs, write_handoff
from .core.partition_merger import merge_partition
from .core.schemas import (
    ACQUISITION_FAILURES_TABLE,
    COMMITTED_CHUNKS_TABLE,
    DOCUMENT_BLOBS_TABLE,
    FILING_OCCURRENCES_TABLE,
)
from .core.snapshot_merge import merge_partitions_to_snapshot
from .core.vacuum import vacuum_snapshots


def _add_plan_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--plan-dir",
        default=None,
        help="Phase 02 finalized target plan directory or plan ID (defaults to latest discovered target plan)",
    )
    parser.add_argument(
        "--plan-id",
        default=None,
        help="Phase 02 target plan ID or prefix",
    )
    parser.add_argument(
        "--scope",
        choices=("deterministic", "policy"),
        default=None,
        help=(
            "target plan selection-scope filter ('deterministic' or 'policy'); "
            "independent of the acquisition mode"
        ),
    )
    parser.add_argument(
        "--output-dir", default=None, help="published partition database directory"
    )


def _resolve_plan_dir(
    plan_dir: str | None = None,
    plan_id: str | None = None,
    scope: str | None = None,
) -> str:
    target_spec = plan_dir or plan_id
    if target_spec and Path(target_spec).is_dir():
        return target_spec

    with suppress(ImportError, OSError, ValueError):
        discovery = importlib.import_module(
            "phases.02_filing_extraction.core.discovery"
        )
        plans = discovery.discover_plans()
        if target_spec:
            for p in plans:
                if p["plan_id"].startswith(target_spec) or target_spec in p["path"]:
                    return p["path"]
            raise ValueError(
                f"Target plan matching {target_spec!r} not found among discovered plans: "
                f"{[p['plan_id'] for p in plans]}"
            )
        if scope:
            scoped_plans = [p for p in plans if p.get("scope") == scope]
            if scoped_plans:
                return scoped_plans[0]["path"]
            raise ValueError(f"No Phase 02 target plan found with scope {scope!r}.")
        if plans:
            return plans[0]["path"]
    raise ValueError(
        "No Phase 02 target plan found. Run Phase 02 target plan or specify --plan-dir / --plan-id."
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
        "--run-id", default=None, help="run ID (defaults to run-<plan_id>)"
    )
    run_parser.add_argument("--base-snapshot", default=None)
    run_parser.add_argument("--artifacts-root", default=None)
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
    merge_partition_parser.add_argument("--partition-count", type=int, default=1)
    merge_partition_parser.add_argument("--run-id", required=True)
    merge_partition_parser.add_argument(
        "--output-dir",
        default=None,
        help="published partition directory (defaults to canonical dataset path)",
    )

    merge_snapshot_parser = subparsers.add_parser(
        "merge-to-snapshot",
        help="publish normalized documents from finalized partition databases",
    )
    merge_snapshot_parser.add_argument(
        "--partition-db",
        action="append",
        default=None,
        help="finalized partition database path; repeat for distributed handoffs",
    )
    merge_snapshot_parser.add_argument(
        "--partition-dir",
        default=None,
        help="directory containing finalized partition databases",
    )
    merge_snapshot_parser.add_argument("--run-id", default=None)
    merge_snapshot_parser.add_argument("--base-snapshot", default=None)
    merge_snapshot_parser.add_argument("--target-mb", type=int, default=96)
    merge_snapshot_parser.add_argument("--artifacts-root", default=None)

    vacuum_parser = subparsers.add_parser(
        "vacuum", help="compact normalized snapshots into one immutable snapshot"
    )
    vacuum_parser.add_argument("--snapshots", nargs="*", default=None)
    vacuum_parser.add_argument("--all", action="store_true", dest="include_all")
    vacuum_parser.add_argument("--workers", type=int, default=None)
    vacuum_parser.add_argument("--target-mb", type=int, default=96)
    vacuum_parser.add_argument("--purge-sources", action="store_true")
    vacuum_parser.add_argument("--purge-dependency-closure", action="store_true")
    vacuum_parser.add_argument("--artifacts-root", default=None)

    status_parser = subparsers.add_parser(
        "status", help="report partition database integrity and record counts"
    )
    status_parser.add_argument(
        "--database", default=None, help="partition database path"
    )
    status_parser.add_argument(
        "--run-id",
        default=None,
        help="transient run ID to inspect",
    )
    status_parser.add_argument("--snapshot", default=None)
    status_parser.add_argument("--artifacts-root", default=None)

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
        help="retry previous acquisition failures",
    )
    fill_fixture_parser.add_argument(
        "--no-progress", action="store_true", help="disable progress tracking"
    )
    return parser


def _fixture_paths(fixtures_arg: str | None) -> list[str] | None:
    if fixtures_arg:
        paths = []
        for item in fixtures_arg.split(","):
            item = item.strip()
            if not item:
                continue
            path = Path(item)
            if path.is_file():
                paths.append(str(path))
            else:
                p_fixture = resolve_paths().fixture(item, dialect="sqlite")
                if p_fixture.db_path.is_file():
                    paths.append(str(p_fixture.db_path))
                else:
                    p_fixture_phase = resolve_paths("webpage_storage").fixture(
                        item, dialect="sqlite"
                    )
                    if p_fixture_phase.db_path.is_file():
                        paths.append(str(p_fixture_phase.db_path))
                    else:
                        paths.append(item)
        return paths

    fixtures_root = (
        resolve_paths("webpage_storage").project.acceptance_root
        / "webpage_storage"
        / "fixtures"
    )
    if fixtures_root.is_dir():
        dbs = [
            str(d / "fixture.sqlite")
            for d in sorted(fixtures_root.iterdir())
            if d.is_dir() and (d / "fixture.sqlite").is_file()
        ]
        if dbs:
            return dbs
    shared_fixtures_root = resolve_paths().fixtures_root
    if shared_fixtures_root.is_dir():
        dbs = [
            str(d / "fixture.sqlite")
            for d in sorted(shared_fixtures_root.iterdir())
            if d.is_dir() and (d / "fixture.sqlite").is_file()
        ]
        if dbs:
            return dbs
    return None


def _resolved_output(args) -> str:
    if getattr(args, "output_dir", None):
        return args.output_dir
    return str(
        resolve_paths().dataset_manifests("webpage_storage", "partition_artifacts")
    )


def _count_table(executor, table: str) -> int:
    query = Select(
        source=Table(table),
        projection=(Aggregate(AggregateFunction.COUNT, Star()),),
    )
    row = executor.query_one(executor.compiler.compile(query))
    if row:
        val = next(iter(row.values()))
        return int(val) if val is not None else 0
    return 0


def _status(database: str | None = None, run_id: str | None = None) -> dict:
    if database:
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
            return {
                "database": database,
                "exists": True,
                "blobs": _count_table(executor, DOCUMENT_BLOBS_TABLE),
                "occurrences": _count_table(executor, FILING_OCCURRENCES_TABLE),
                "failures": _count_table(executor, ACQUISITION_FAILURES_TABLE),
                "committed_chunks": _count_table(executor, COMMITTED_CHUNKS_TABLE),
            }
        finally:
            executor.close()

    target_run_id = run_id or "run-default"
    run_paths = resolve_paths("webpage_storage", target_run_id)
    meta_file = run_paths.run_root / "run_metadata.json"
    meta = {}
    if meta_file.is_file():
        with suppress(Exception):
            from defs.storage import load_json

            meta = load_json(meta_file)

    chunk_dbs = [
        p for p in sorted(run_paths.workers_root.rglob("chunk-*.db")) if p.is_file()
    ]
    return {
        "run_id": target_run_id,
        "exists": run_paths.run_root.exists(),
        "metadata": meta,
        "chunk_dbs_count": len(chunk_dbs),
    }


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "preview":
            plan_dir = _resolve_plan_dir(
                getattr(args, "plan_dir", None),
                getattr(args, "plan_id", None),
                getattr(args, "scope", None),
            )
            locators, occurrences, plan = pipeline.load_targets(plan_dir)
            selected = pipeline.partition_locators(
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
            plan_dir = _resolve_plan_dir(
                getattr(args, "plan_dir", None),
                getattr(args, "plan_id", None),
                getattr(args, "scope", None),
            )
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
                selected = pipeline.partition_locators(
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
                    processors_mod = importlib.import_module(
                        "phases.025_webpage_storage.processors"
                    )
                    processor = processors_mod.DefaultFilingProcessor()
                    plan_id = (
                        pipeline.load_targets(plan_dir)[2].get("plan_id")
                        or Path(plan_dir).name
                    )
                    result = pipeline.run_partition(
                        plan_dir,
                        _resolved_output(args),
                        mode=args.mode,
                        fixture_paths=_fixture_paths(getattr(args, "fixtures", None)),
                        http_client=http_client,
                        run_id=args.run_id or f"run-{plan_id}",
                        partition_id=args.partition_id,
                        partition_count=args.partition_count,
                        chunk_size=args.chunk_size,
                        workers=workers,
                        progress=progress_cb,
                        processor=processor,
                        base_snapshot_id=args.base_snapshot,
                        artifacts_root=args.artifacts_root,
                    )
                finally:
                    if pbar is not None:
                        pbar.close()

            print_json(result)
            return 0
        if args.command == "merge-to-snapshot":
            paths: list[Path] = []
            for value in args.partition_db or []:
                path = Path(value)
                if not path.is_file():
                    raise FileNotFoundError(f"partition database not found: {path}")
                paths.append(path)
            if args.partition_dir:
                paths.extend(
                    sorted(Path(args.partition_dir).rglob("partition-*.sqlite"))
                )
            if not paths and args.run_id:
                run_paths = resolve_paths("webpage_storage", args.run_id)
                paths.extend(sorted(run_paths.run_root.rglob("partition-*.sqlite")))
            if not paths:
                raise ValueError(
                    "merge-to-snapshot requires finalized partition databases"
                )
            handoff_paths = [path for path in paths if handoff_path(path).is_file()]
            if handoff_paths:
                if len(handoff_paths) != len(paths):
                    raise ValueError("all partition databases need handoff manifests")
                validate_handoffs(paths)
            root = Path(args.artifacts_root or resolve_paths().artifacts_root)
            base = args.base_snapshot
            if base is None:
                pointer = get_current_snapshot_pointer(
                    root, phase="webpage_storage", dataset="normalized_documents"
                )
                base = pointer.get("snapshot_id") if pointer else None
            manifest = merge_partitions_to_snapshot(
                paths,
                artifacts_root=root,
                base_snapshot_id=base,
                target_bytes=max(1, args.target_mb) * 1024 * 1024,
            )
            print_json(manifest)
            return 0
        if args.command == "vacuum":
            root = Path(args.artifacts_root or resolve_paths().artifacts_root)
            workers = args.workers
            if workers is None:
                workers = max(1, derive_resources().workers)
            manifest = vacuum_snapshots(
                artifacts_root=root,
                snapshot_ids=args.snapshots,
                include_all=args.include_all,
                workers=workers,
                target_bytes=max(1, args.target_mb) * 1024 * 1024,
                purge_sources=args.purge_sources,
                purge_dependency_closure=args.purge_dependency_closure,
            )
            print_json(manifest)
            return 0
        if args.command == "merge-partition":
            run_paths = resolve_paths("webpage_storage", args.run_id)
            chunk_dbs = [
                p
                for p in sorted(run_paths.workers_root.rglob("chunk-*.db"))
                if p.is_file()
            ]
            output = Path(_resolved_output(args))
            output.mkdir(parents=True, exist_ok=True)
            partition_name = (
                resolve_paths()
                .dataset_manifests(
                    "webpage_storage",
                    "partition_artifacts",
                    f"partition-{args.partition_id:05d}",
                )
                .name
                + ".sqlite"
            )
            merge_result = merge_partition(output / partition_name, chunk_dbs)
            handoff = write_handoff(
                output / partition_name,
                plan_id=None,
                run_id=args.run_id,
                partition_id=args.partition_id,
                partition_count=args.partition_count,
                merge_result=merge_result,
            )
            print_json({**merge_result.to_dict(), "partition_handoff": handoff})
            return 0
        if args.command == "status":
            if args.snapshot is not None:
                from .core.snapshot import SnapshotReader

                root = Path(args.artifacts_root or resolve_paths().artifacts_root)
                reader = SnapshotReader(root, args.snapshot)
                rows = reader.index_rows()
                print_json(
                    {
                        "snapshot_id": reader.snapshot_id,
                        "logical_fingerprint": reader.manifest.get(
                            "logical_fingerprint"
                        ),
                        "part_count": len(reader.manifest.get("resolved_parts", [])),
                        "occurrence_count": len(rows),
                        "payload_count": len({row["doc_id"] for row in rows}),
                    }
                )
                return 0
            print_json(_status(args.database, args.run_id))
            return 0
        if args.command == "fill-fixture":
            from .core.fixture_builder import fill_fixture

            plan_dir = _resolve_plan_dir(
                getattr(args, "plan_dir", None),
                getattr(args, "plan_id", None),
                getattr(args, "scope", None),
            )
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
