"""Command surface for the filing-catalog pipeline.

Three commands: ``materialize`` turns a finalized Phase 1 snapshot into an
immutable catalog snapshot, ``plan`` slices that catalog into an immutable
target plan, and ``status`` reports published state from manifests only.

There is deliberately no ``run`` command. Nothing in this phase performs network
work, so the resumable-chunk lifecycle of Phase 1 has no analogue here.

There is also deliberately no date flag on ``plan``. Deterministic planning
accepts exactly four filters; date slicing belongs to the Stage B selection
engine, and passing a date to this command is an error rather than a no-op.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from edgar_sec.pipelines.filing_catalog.catalog_job import (
    CatalogError,
    materialize,
)
from edgar_sec.pipelines.filing_catalog.discovery import status as build_status
from edgar_sec.pipelines.filing_catalog.paths import resolve_filing_catalog_paths
from edgar_sec.pipelines.filing_catalog.planner import plan as build_plan
from edgar_sec.pipelines.filing_catalog.publication import PlanConflictError

__all__ = ["build_parser", "main"]


def _emit_progress(event: dict[str, Any]) -> None:
    """Write progress to stderr so stdout carries only the JSON result.

    Keeping the two streams separate is what makes ``... | jq`` work; mixing a
    human-readable trace into stdout would corrupt the payload.
    """
    stage = event.get("stage", "")
    rows = event.get("rows")
    suffix = f" ({rows} rows)" if isinstance(rows, int) else ""
    print(f"[filing-catalog] {stage}{suffix}", file=sys.stderr)


def _resolve_artifacts(value: str) -> Path | None:
    return Path(value).resolve() if value else None


def cmd_materialize(args: argparse.Namespace) -> int:
    try:
        manifest = materialize(
            args.source or None,
            _resolve_artifacts(args.artifacts),
            source_manifest=args.source_manifest or None,
            source_batch_size=args.batch_size,
            progress=_emit_progress,
        )
    except CatalogError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    try:
        plan = build_plan(
            args.catalog,
            _resolve_artifacts(args.artifacts),
            forms=tuple(args.forms) if args.forms else None,
            amendment=args.amendment,
            document_suffixes=tuple(args.suffixes) if args.suffixes else None,
            limit=args.limit,
            progress=_emit_progress,
        )
    except (PlanConflictError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(plan, indent=2, sort_keys=True))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    paths = resolve_filing_catalog_paths(_resolve_artifacts(args.artifacts))
    print(json.dumps(build_status(paths), indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="filing-catalog",
        description="Materialize filing catalogs and deterministic target plans",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    materialize_parser = subparsers.add_parser(
        "materialize", help="build a catalog snapshot from a Phase 1 snapshot"
    )
    materialize_parser.add_argument(
        "--source", default="", help="Phase 1 metadata.parquet path"
    )
    materialize_parser.add_argument(
        "--source-manifest", default="", help="Phase 1 snapshot manifest path"
    )
    materialize_parser.add_argument(
        "--artifacts", default="", help="artifacts root override"
    )
    materialize_parser.add_argument(
        "--batch-size", type=int, default=None, help="registrant rows staged per batch"
    )
    materialize_parser.set_defaults(func=cmd_materialize)

    plan_parser = subparsers.add_parser(
        "plan", help="publish a deterministic target plan"
    )
    plan_parser.add_argument("--catalog", required=True, help="catalog id or 'current'")
    plan_parser.add_argument("--artifacts", default="", help="artifacts root override")
    plan_parser.add_argument(
        "--forms", nargs="*", default=[], help="restrict to these form types"
    )
    plan_parser.add_argument(
        "--amendment",
        default="both",
        choices=["both", "original", "amendments"],
        help="amendment policy",
    )
    plan_parser.add_argument(
        "--suffixes",
        nargs="*",
        default=[],
        help="allowed document suffixes, e.g. .htm .txt",
    )
    plan_parser.add_argument(
        "--limit", type=int, default=None, help="max rows per form partition"
    )
    plan_parser.set_defaults(func=cmd_plan)

    status_parser = subparsers.add_parser(
        "status", help="report published catalogs and plans from manifests"
    )
    status_parser.add_argument(
        "--artifacts", default="", help="artifacts root override"
    )
    status_parser.set_defaults(func=cmd_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    parsed = parser.parse_args(args)
    return int(parsed.func(parsed))
