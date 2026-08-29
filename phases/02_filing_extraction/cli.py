"""Canonical Phase 2 command surface."""

from __future__ import annotations

import argparse
import json
import sys

from .core import config as phase_config
from .core import discovery
from .core.materialize import materialize
from .core.target_plan import plan


def _stderr_progress(event: dict) -> None:
    """Report stage events on stderr; stdout stays pure JSON for automation."""
    if event.get("type") == "batch_done":
        batch = event.get("batch")
        total = event.get("total_batches")
        batch_str = f"batch {batch}/{total}" if total else f"batch {batch}"
        ciks_done = event.get("ciks_done")
        total_ciks = event.get("total_ciks")
        pct_str = (
            f" ({ciks_done * 100 / total_ciks:.1f}%)"
            if (ciks_done and total_ciks)
            else ""
        )
        print(
            f"progress: {batch_str}{pct_str} "
            f"(CIK {event.get('cik_start')}..{event.get('cik_end')}, "
            f"rows={event.get('rows')})",
            file=sys.stderr,
        )
        return
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
    materialize_parser.add_argument("--config", default=None)
    materialize_parser.add_argument("--output-root", default=None)
    materialize_parser.add_argument(
        "--progress",
        action="store_true",
        help="report stage progress on stderr",
    )
    materialize_parser.add_argument("--source-batch-size", type=int, default=None)
    materialize_parser.add_argument("--threads", type=int, default=None)
    materialize_parser.add_argument("--memory-limit", default=None)
    materialize_parser.add_argument("--temp-directory", default=None)
    plan_parser = commands.add_parser("plan")
    plan_parser.add_argument("--catalog", required=True)
    plan_parser.add_argument("--output-root", default=None)
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
    status_parser.add_argument("--manifests-root", default=None)
    status_parser.add_argument("--runs-root", default=None)
    args = parser.parse_args(argv)
    if args.command == "materialize":
        config = phase_config.load(args.config)
        result = materialize(
            args.source_artifact,
            args.output_root,
            source_manifest=args.source_manifest,
            progress=_stderr_progress if args.progress else None,
            source_batch_size=(
                args.source_batch_size
                if args.source_batch_size is not None
                else config.source_batch_size
            ),
            threads=args.threads,
            memory_limit=args.memory_limit,
            temp_directory=args.temp_directory,
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
        result = discovery.status(args.manifests_root, args.runs_root)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
