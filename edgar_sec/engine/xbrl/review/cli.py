"""Command-line entrypoint for XBRL review runs and benchmark validation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths
from edgar_sec.engine.xbrl.review.review import promote_review_rule
from edgar_sec.engine.xbrl.storage.review_artifacts.adapter import (
    XbrlReviewAdapter,
)
from edgar_sec.infra.storage.review.cli import attach_review_artifact_subparsers


def _cmd_promote(args: argparse.Namespace) -> int:
    """Execute rule promotion into the canonical knowledge base."""
    rec = promote_review_rule(
        args.rule_id,
        args.run_dir,
        db_path=args.db_path,
    )
    print(f"Promoted rule: {rec.rule_id} -> {rec.target_concept}")
    return 0


def _cmd_benchmark(args: argparse.Namespace) -> int:
    """Execute XBRL semantic benchmark across a designated cohort."""
    from edgar_sec.engine.xbrl.review.benchmark import execute_cohort_benchmark

    paths = resolve_xbrl_paths()
    cohort_p = (
        args.cohort_file
        if args.cohort_file is not None
        else paths.default_seed_cohort_path
    )
    report = execute_cohort_benchmark(cohort_source=cohort_p)
    return 0 if report.failed_tests == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for XBRL commands."""
    parser = argparse.ArgumentParser(
        prog="xbrl",
        description="XBRL Semantic Lattice Review, Staging, and Benchmark CLI",
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    adapter = XbrlReviewAdapter()
    rev_commands = attach_review_artifact_subparsers(sub, adapter)

    prom_p = rev_commands.add_parser("promote", help="promote candidate rule to KB")
    prom_p.add_argument("--rule-id", required=True, help="hypothesis rule ID")
    prom_p.add_argument(
        "--run-dir", type=Path, required=True, help="review run directory"
    )
    prom_p.add_argument("--db-path", type=Path, help="target DuckDB database path")
    prom_p.set_defaults(func=_cmd_promote)

    bench_p = sub.add_parser(
        "benchmark", help="execute XBRL semantic benchmark validation"
    )
    bench_p.add_argument("--cohort-file", type=Path, help="path to cohort JSON file")
    bench_p.set_defaults(func=_cmd_benchmark)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Execute XBRL CLI commands based on command line arguments."""
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    if hasattr(args, "func"):
        return int(args.func(args))
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
