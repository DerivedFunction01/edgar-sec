"""Thin bounded SEC-backed smoke-test shim.

    python -m phases.01_metadata_extraction.smoke_test \
        --input uploads/cik-sec.csv --sample-size 3 \
        --artifacts .artifacts/metadata/preview/<run-id>

Defaults to the preview artifacts root plus a small sample. Exits nonzero
when any sampled CIK fails or configuration is invalid.
"""

from __future__ import annotations

import argparse
import logging
import sys

from .core import DEFAULT_PREVIEW_ARTIFACTS, RunOptions, preview_sample


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="phases.01_metadata_extraction.smoke_test")
    parser.add_argument("--input", default=RunOptions.input_path)
    parser.add_argument(
        "--artifacts",
        default=DEFAULT_PREVIEW_ARTIFACTS,
        help="preview output directory (never the production phase output)",
    )
    parser.add_argument("--sample-size", type=int, default=3)
    parser.add_argument(
        "--storage-format",
        choices=("parquet", "jsonl"),
        default=RunOptions.storage_format,
        help="preview artifact format",
    )
    parser.add_argument("--timeout", type=float, default=RunOptions.timeout_s)
    parser.add_argument("--max-retries", type=int, default=RunOptions.max_retries)
    parser.add_argument("--rate-limit", type=float, default=RunOptions.rate_limit_rps)
    parser.add_argument("--user-agent", default="")
    parser.add_argument("--cache-dir", default="")
    parser.add_argument(
        "--max-failure-attempts", type=int, default=RunOptions.max_failure_attempts
    )
    parser.add_argument("--ignore-failure-history", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--log-level", default="INFO")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(levelname)s %(message)s",
    )
    options = RunOptions(
        input_path=args.input,
        artifacts_dir=args.artifacts,
        storage_format=args.storage_format,
        timeout_s=args.timeout,
        max_retries=args.max_retries,
        rate_limit_rps=args.rate_limit,
        user_agent=args.user_agent,
        cache_dir=args.cache_dir,
        max_failure_attempts=args.max_failure_attempts,
        ignore_failure_history=getattr(args, "ignore_failure_history", False),
        limit=args.limit,
    )
    try:
        options.validate()
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        result = preview_sample(options, sample_size=args.sample_size)
    except Exception as exc:  # noqa: BLE001  # network or unexpected failure
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    failed = [item for item in result["sample"] if item["status"] == "failed"]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
