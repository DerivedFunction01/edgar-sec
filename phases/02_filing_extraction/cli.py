"""Canonical Phase 2 command surface."""

from __future__ import annotations

import argparse
import json
import sys

from .core import discovery
from .core.materialize import materialize
from .core.target_plan import plan


def _stderr_progress(event: dict) -> None:
    """Report stage events on stderr; stdout stays pure JSON for automation."""
    if event.get("type") == "merge_stage":
        stage = event.get("stage", "")
        rows = event.get("rows")
        suffix = f" (rows={rows})" if rows is not None else ""
        print(f"progress: {stage}{suffix}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="phases.02_filing_extraction")
    commands = parser.add_subparsers(dest="command", required=True)
    materialize_parser = commands.add_parser("materialize")
    materialize_parser.add_argument("--source-artifact")
    materialize_parser.add_argument("--source-manifest")
    materialize_parser.add_argument(
        "--output-root", default=".artifacts/filing_extraction/catalogs"
    )
    materialize_parser.add_argument(
        "--progress",
        action="store_true",
        help="report stage progress on stderr",
    )
    plan_parser = commands.add_parser("plan")
    plan_parser.add_argument("--catalog", required=True)
    plan_parser.add_argument(
        "--output-root", default=".artifacts/filing_extraction/runs"
    )
    plan_parser.add_argument("--form", action="append", default=[])
    plan_parser.add_argument(
        "--amendment", choices=("both", "original", "amendments"), default="both"
    )
    plan_parser.add_argument("--limit", type=int)
    plan_parser.add_argument(
        "--progress",
        action="store_true",
        help="report stage progress on stderr",
    )
    status_parser = commands.add_parser("status")
    status_parser.add_argument("--catalogs-root", default=None)
    status_parser.add_argument("--runs-root", default=None)
    args = parser.parse_args(argv)
    if args.command == "materialize":
        result = materialize(
            args.source_artifact,
            args.output_root,
            source_manifest=args.source_manifest,
            progress=_stderr_progress if args.progress else None,
        )
    elif args.command == "plan":
        result = plan(
            args.catalog,
            args.output_root,
            forms=tuple(args.form),
            amendment=args.amendment,
            limit=args.limit,
            progress=_stderr_progress if args.progress else None,
        )
    else:
        result = discovery.status(args.catalogs_root, args.runs_root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
