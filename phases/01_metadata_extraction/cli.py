"""Operator-facing argparse entry point.

Usage (from the repository root):

    python -m phases.01_metadata_extraction.cli plan \
        --input uploads/cik-sec.csv --artifacts .artifacts/metadata/preview/<run-id> \
        --chunk-size 1000

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

from .core import MergeError, RunOptions, build_plan, get_status, merge, preview_sample


def add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input", default=RunOptions.input_path, help="CIK/name CSV manifest")
    parser.add_argument("--artifacts", default=RunOptions.artifacts_dir, help="run artifacts directory")
    parser.add_argument("--chunk-size", type=int, default=RunOptions.chunk_size)
    parser.add_argument("--workers", type=int, default=RunOptions.workers)
    parser.add_argument("--timeout", type=float, default=RunOptions.timeout_s)
    parser.add_argument("--max-retries", type=int, default=RunOptions.max_retries)
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=RunOptions.rate_limit_rps,
        help="target requests per second for this process",
    )
    parser.add_argument(
        "--user-agent",
        default="",
        help="stable SEC identity: 'AppName/1.0 contact@example.com' (or SEC_USER_AGENT)",
    )
    parser.add_argument("--cache-dir", default="", help="optional raw response cache directory")
    parser.add_argument("--limit", type=int, default=None, help="bounded test run size")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--run-id", default="local")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="phases.01_metadata_extraction.cli")
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="validate input, assign chunks, write plan.json (no network)")
    add_common_options(plan_parser)

    preview_parser = subparsers.add_parser("preview", help="small SEC-backed smoke test")
    add_common_options(preview_parser)
    preview_parser.add_argument("--sample-size", type=int, default=3)

    status_parser = subparsers.add_parser("status", help="report run progress and mergeability")
    status_parser.add_argument("--artifacts", required=True)

    merge_parser = subparsers.add_parser("merge", help="validate and merge completed chunks")
    merge_parser.add_argument("--artifacts", required=True)
    merge_parser.add_argument("--output", required=True)
    merge_parser.add_argument(
        "--allow-accession-duplicates",
        action="store_true",
        help="permit duplicate nested accessions (recorded in the merge report)",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    log_level = getattr(args, "log_level", "INFO")
    logging.basicConfig(level=getattr(logging, log_level.upper(), logging.INFO), format="%(levelname)s %(message)s")

    options = RunOptions(
        input_path=getattr(args, "input", RunOptions.input_path),
        artifacts_dir=args.artifacts,
        chunk_size=getattr(args, "chunk_size", RunOptions.chunk_size),
        workers=getattr(args, "workers", RunOptions.workers),
        timeout_s=getattr(args, "timeout", RunOptions.timeout_s),
        max_retries=getattr(args, "max_retries", RunOptions.max_retries),
        rate_limit_rps=getattr(args, "rate_limit", RunOptions.rate_limit_rps),
        user_agent=getattr(args, "user_agent", ""),
        cache_dir=getattr(args, "cache_dir", ""),
        limit=getattr(args, "limit", None),
        log_level=args.log_level if hasattr(args, "log_level") else "INFO",
        run_id=getattr(args, "run_id", "local"),
    )

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
        if args.command == "status":
            status = get_status(options)
            print(json.dumps(status, indent=2, sort_keys=True))
            return 0
        if args.command == "merge":
            report = merge(options, args.output, allow_accession_duplicates=args.allow_accession_duplicates)
            print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
            return 0
    except (MergeError, ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
