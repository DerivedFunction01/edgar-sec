"""Canonical Phase 2.5 command surface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from defs.runtime.cli import print_json
from defs.runtime.paths import resolve_paths
from defs.sql import Select, SqlDialect, Table, col, make_sql_executor

from .core import pipeline
from .core.partition_merger import merge_partition
from .core.schemas import DOCUMENT_BLOBS_TABLE


def _add_plan_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--plan-dir", required=True, help="Phase 02 finalized target plan directory"
    )
    parser.add_argument(
        "--output-dir", default=None, help="published partition database directory"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="phases.025_webpage_storage.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    preview_parser = subparsers.add_parser(
        "preview", help="enumerate planned acquisitions from a Phase 02 target plan"
    )
    _add_plan_args(preview_parser)
    preview_parser.add_argument("--partition-count", type=int, default=1)
    preview_parser.add_argument("--chunk-size", type=int, default=100)

    run_parser = subparsers.add_parser("run", help="acquire and store one partition")
    _add_plan_args(run_parser)
    run_parser.add_argument(
        "--mode", choices=("fixture", "production"), default="fixture"
    )
    run_parser.add_argument("--partition-id", type=int, default=1)
    run_parser.add_argument("--partition-count", type=int, default=1)
    run_parser.add_argument("--chunk-size", type=int, default=100)
    run_parser.add_argument("--run-id", default="local")
    run_parser.add_argument(
        "--fixtures", default=None, help="comma-separated fixture ids for fixture mode"
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
    return parser


def _fixture_paths(fixtures: str | None):
    if not fixtures:
        return None
    return [
        resolve_paths().fixture(fid.strip(), dialect="sqlite").db_path
        for fid in fixtures.split(",")
        if fid.strip()
    ]


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
        return {"database": database, "exists": False, "blobs": 0}
    executor = make_sql_executor(database, dialect=SqlDialect.SQLITE)
    try:
        rows = executor.query(
            executor.compiler.compile(
                Select(source=Table(DOCUMENT_BLOBS_TABLE), projection=(col("doc_id"),))
            )
        )
        return {"database": database, "exists": True, "blobs": len(rows)}
    finally:
        executor.close()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "preview":
            locators, occurrences, plan = pipeline.load_targets(args.plan_dir)
            print_json(
                {
                    "locator_count": len(locators),
                    "occurrence_count": len(occurrences),
                    "plan_scope": plan.get("scope"),
                    "partition_count": args.partition_count,
                    "chunk_size": args.chunk_size,
                }
            )
            return 0
        if args.command == "run":
            result = pipeline.run_partition(
                args.plan_dir,
                _resolved_output(args),
                mode=args.mode,
                fixture_paths=_fixture_paths(getattr(args, "fixtures", None)),
                run_id=args.run_id,
                partition_id=args.partition_id,
                partition_count=args.partition_count,
                chunk_size=args.chunk_size,
            )
            print_json(result)
            return 0
        if args.command == "merge-partition":
            run_paths = resolve_paths("webpage_storage", args.run_id)
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
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print("error: unknown command", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
