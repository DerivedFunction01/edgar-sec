"""Unified command surface for the feeds ledger pipeline.

Every command is a plain callable over one typed options model, so the
operator and the CLI are one code path.
"""

from __future__ import annotations

import argparse
import sys

from edgar_sec.domain.feeds.models import STRUCTURED_FEED_SOURCES
from edgar_sec.infra.storage.dag.cli import (
    attach_dag_subparser,
    dispatch_dag_subcommand,
)

from .commands.backfill import cmd_backfill
from .commands.run import cmd_run
from .commands.status import cmd_status
from .options import FeedsOptions, feeds_options, parse_month
from .paths import resolve_feeds_paths
from .specs import FEED_RELATION_SPECS

__all__ = ["build_parser", "main"]


def _add_common(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--artifacts", default="", help="artifacts root override")
    sub.add_argument(
        "--branch", default="main", help="DAG branch to advance (default: main)"
    )


def _options(args: argparse.Namespace) -> FeedsOptions:
    return feeds_options(
        artifacts_root=args.artifacts or None,
        feeds=tuple(
            feed.strip()
            for feed in str(getattr(args, "feeds", "") or "").split(",")
            if feed.strip()
        )
        or STRUCTURED_FEED_SOURCES,
        start=parse_month(args.start) if getattr(args, "start", "") else None,
        end=parse_month(args.end) if getattr(args, "end", "") else None,
        branch=getattr(args, "branch", "main") or "main",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the feeds ledger argument parser."""
    parser = argparse.ArgumentParser(
        prog="feeds", description="SEC structured-disclosure feed ledger pipeline"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run", help="fetch the live feeds and publish new ledger events"
    )
    _add_common(run_parser)
    run_parser.add_argument(
        "--feeds",
        default="",
        help="comma-separated live feed names; defaults to all four",
    )
    run_parser.set_defaults(func=lambda args: cmd_run(_options(args)))

    backfill_parser = subparsers.add_parser(
        "backfill", help="publish monthly-archive events for a month range"
    )
    _add_common(backfill_parser)
    backfill_parser.add_argument("--start", required=True, help="first month, YYYY-MM")
    backfill_parser.add_argument("--end", required=True, help="last month, YYYY-MM")
    backfill_parser.set_defaults(func=lambda args: cmd_backfill(_options(args)))

    status_parser = subparsers.add_parser(
        "status", help="report the ledger tip and per-source counts"
    )
    _add_common(status_parser)
    status_parser.set_defaults(func=lambda args: cmd_status(_options(args)))

    dag_parser = attach_dag_subparser(
        subparsers,
        subcommand_name="dag",
        default_root=lambda: resolve_feeds_paths().snapshots_root,
        default_specs=FEED_RELATION_SPECS,
    )
    dag_parser.set_defaults(
        func=lambda args: dispatch_dag_subcommand(
            args,
            default_root=lambda: resolve_feeds_paths().snapshots_root,
            default_specs=FEED_RELATION_SPECS,
        )
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
