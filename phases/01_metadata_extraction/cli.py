"""Operator-facing argparse entry point.

Usage (from the repository root):

    python -m phases.01_metadata_extraction.cli plan \
        --config .artifacts/metadata/config.json

    python -m phases.01_metadata_extraction.cli status --artifacts <run-dir>
    python -m phases.01_metadata_extraction.cli merge --artifacts <run-dir> \
        --output phases/01_metadata_extraction/output/merged/submission_metadata.parquet
    python -m phases.01_metadata_extraction.cli preview --sample-size 3
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from defs.runtime.cli import (
    add_common_options as add_runtime_common_options,
)
from defs.runtime.cli import (
    coalesce,
    load_config_or_template,
)

from .core import (
    PROJECT_CONFIG_DEFAULT_PATH,
    RunOptions,
    build_plan,
    default_project_config,
    default_user_agent,
    get_status,
    load_project_config,
    merge,
    merge_one_partition,
    preview_sample,
    run_partition,
    write_project_config,
)
from .core.merge import MergeError


def add_common_options(parser: argparse.ArgumentParser, **kwargs) -> None:
    add_runtime_common_options(parser, **kwargs)


def options_from_args(args, project_config) -> RunOptions:
    return RunOptions(
        input_path=coalesce(
            getattr(args, "input", None),
            project_config.input_path,
            RunOptions.input_path,
        ),
        artifacts_dir=coalesce(
            getattr(args, "artifacts", None),
            project_config.artifacts_dir,
            RunOptions.artifacts_dir,
        ),
        chunk_size=coalesce(
            getattr(args, "chunk_size", None),
            project_config.chunk_size,
            RunOptions.chunk_size,
        ),
        partition_count=coalesce(
            getattr(args, "partition_count", None),
            project_config.partition_count,
            RunOptions.partition_count,
        ),
        partition_id=getattr(args, "partition_id", None),
        storage_format=coalesce(
            getattr(args, "storage_format", None),
            project_config.storage_format,
            RunOptions.storage_format,
        ),
        workers=coalesce(
            getattr(args, "workers", None), project_config.workers, RunOptions.workers
        ),
        timeout_s=coalesce(
            getattr(args, "timeout", None),
            project_config.timeout_s,
            RunOptions.timeout_s,
        ),
        max_retries=coalesce(
            getattr(args, "max_retries", None),
            project_config.max_retries,
            RunOptions.max_retries,
        ),
        rate_limit_rps=coalesce(
            getattr(args, "rate_limit", None),
            project_config.rate_limit_rps,
            RunOptions.rate_limit_rps,
        ),
        user_agent=(
            getattr(args, "user_agent", None)
            or project_config.user_agent
            or default_user_agent()
        ),
        cache_dir=coalesce(
            getattr(args, "cache_dir", None), project_config.cache_dir, ""
        ),
        max_failure_attempts=coalesce(
            getattr(args, "max_failure_attempts", None),
            project_config.max_failure_attempts,
            RunOptions.max_failure_attempts,
        ),
        limit=coalesce(
            getattr(args, "limit", None), project_config.limit, RunOptions.limit
        ),
        log_level=getattr(args, "log_level", "INFO"),
        run_id=getattr(args, "run_id", "local"),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="phases.01_metadata_extraction.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser(
        "plan", help="validate input, assign chunks, write plan.json (no network)"
    )
    add_common_options(plan_parser)

    preview_parser = subparsers.add_parser(
        "preview", help="small SEC-backed smoke test"
    )
    add_common_options(preview_parser)
    preview_parser.add_argument("--sample-size", type=int, default=3)

    run_parser = subparsers.add_parser(
        "run", help="run all missing chunks in one operational partition"
    )
    add_common_options(run_parser)

    status_parser = subparsers.add_parser(
        "status", help="report run progress and mergeability"
    )
    status_parser.add_argument(
        "--config",
        default=PROJECT_CONFIG_DEFAULT_PATH,
        help="path to persisted project configuration",
    )
    status_parser.add_argument("--partition-id", type=int, default=None)
    status_parser.add_argument("--artifacts", required=True)
    status_parser.add_argument(
        "--storage-format",
        choices=("parquet", "jsonl"),
        default=None,
        help="checkpoint format used by the run",
    )

    merge_parser = subparsers.add_parser(
        "merge", help="validate and merge complete partition artifacts"
    )
    merge_parser.add_argument(
        "--config",
        default=PROJECT_CONFIG_DEFAULT_PATH,
        help="path to persisted project configuration",
    )
    merge_parser.add_argument("--artifacts", required=True)
    merge_parser.add_argument("--output", required=True)
    merge_parser.add_argument(
        "--storage-format",
        choices=("parquet", "jsonl"),
        default=None,
        help="checkpoint format (defaults to plan.json's recorded format)",
    )
    merge_parser.add_argument(
        "--output-storage-format",
        choices=("parquet",),
        default=None,
        help="final output format (Parquet only; defaults to the output suffix)",
    )
    merge_partition_parser = subparsers.add_parser(
        "merge-partition", help="merge one partition's chunks into a complete artifact"
    )
    add_common_options(merge_partition_parser, include_partition=False)
    merge_partition_parser.add_argument("--partition-id", type=int, required=True)
    merge_partition_parser.add_argument("--output", default=None)
    merge_partition_parser.add_argument(
        "--output-storage-format", choices=("parquet",), default=None
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    log_level = getattr(args, "log_level", "INFO")
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(levelname)s %(message)s",
    )

    config_path = args.config or PROJECT_CONFIG_DEFAULT_PATH
    project_config, _ = load_config_or_template(
        config_path,
        load=load_project_config,
        write=write_project_config,
        default=default_project_config,
    )

    options = options_from_args(args, project_config)

    try:
        if args.command == "plan":
            options.validate()
            plan = build_plan(options)
            print(
                json.dumps(
                    {
                        "rows": plan["row_count"],
                        "chunks": len(plan["chunks"]),
                        "plan_hash": plan["plan_hash"],
                        "input_fingerprint": plan["input_fingerprint"],
                    },
                    indent=2,
                )
            )
            return 0
        if args.command == "preview":
            options.validate()
            result = preview_sample(options, sample_size=args.sample_size)
            failed = [item for item in result["sample"] if item["status"] == "failed"]
            return 1 if failed else 0
        if args.command == "run":
            options.validate()
            if args.partition_id is None:
                raise ValueError("--partition-id is required for run")
            result = run_partition(options, args.partition_id)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        if args.command == "status":
            status = get_status(options, partition_id=args.partition_id)
            print(json.dumps(status, indent=2, sort_keys=True))
            return 0
        if args.command == "merge":
            report = merge(
                options,
                args.output,
                storage_format=args.storage_format,
                output_storage_format=args.output_storage_format,
            )
            print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
            return 0
        if args.command == "merge-partition":
            options.validate()
            report = merge_one_partition(
                options,
                args.partition_id,
                output_path=args.output,
                storage_format=args.storage_format,
                output_storage_format=args.output_storage_format,
            )
            print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
            return 0
    except (ValueError, FileNotFoundError, MergeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
