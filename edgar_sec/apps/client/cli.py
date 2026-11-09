"""CLI entry point for high-throughput end-to-end filing acquisition."""

from __future__ import annotations

import argparse
import json
import sys

from edgar_sec.apps.client.facade import Edgar
from edgar_sec.apps.client.models import FilingsResult
from edgar_sec.apps.runner.coordinator import ProfileResolutionError
from edgar_sec.pipelines.document_planning.planner import DocumentPlanningError

_MAX_GRID_ROWS = 10


def build_parser() -> argparse.ArgumentParser:
    """Build the fetch argument parser."""
    parser = argparse.ArgumentParser(
        prog="fetch",
        description="Acquire and process SEC filings end-to-end into DataFrames",
        allow_abbrev=False,
        epilog=(
            "Operator surfaces (handled before this parser): "
            "run with no arguments for the interactive menu; "
            "--list-operations [--json] lists every operation; "
            "--op <id> [--options '<json>'] [--json] runs one operation; "
            "--op <id> --help shows one operation's fields; "
            "--config <file> [--mode <mode>] [--snapshot <id>] "
            "[--workers <n>] [--json] runs a config file."
        ),
    )
    parser.add_argument("--forms", nargs="+", help="Filing form types")
    parser.add_argument("--ciks", nargs="+", help="Company CIKs")
    parser.add_argument("--tickers", nargs="+", help="Company tickers")
    parser.add_argument("--accessions", nargs="+", help="Accession numbers")
    parser.add_argument("--dates", help="Date selection range (e.g. 2024)")
    parser.add_argument("--suffixes", nargs="+", help="Document suffixes")
    parser.add_argument("--limit", type=int, help="Maximum accessions to acquire")
    parser.add_argument(
        "--roles",
        nargs="+",
        default=["primary"],
        help="Target roles: primary or exhibit types",
    )
    parser.add_argument(
        "--operation",
        default="raw",
        choices=["raw", "render_to_xml", "render_to_txt"],
        help="Acquisition operation",
    )
    parser.add_argument(
        "--mode",
        default="fast",
        choices=["fast", "pipeline", "snapshot"],
        help="Engine mode: fast catalog, full pipeline, or snapshot",
    )
    parser.add_argument(
        "--snapshot",
        default="main",
        help="Snapshot id, tag, or branch for snapshot mode",
    )
    parser.add_argument(
        "--file",
        help="Input file of targets; routes to fetch_from_file",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Output summary as JSON",
    )
    return parser


def _fetch_kwargs(args: argparse.Namespace) -> dict[str, object]:
    return {
        "forms": tuple(args.forms or ()),
        "ciks": tuple(args.ciks or ()),
        "tickers": tuple(args.tickers or ()),
        "accessions": tuple(args.accessions or ()),
        "dates": args.dates,
        "suffixes": tuple(args.suffixes or ()),
        "roles": tuple(args.roles or ("primary",)),
        "limit": args.limit,
        "operation": args.operation,
        "mode": args.mode,
        "snapshot": args.snapshot,
    }


def _file_kwargs(args: argparse.Namespace) -> dict[str, object]:
    return {
        "file_path": args.file,
        "forms": tuple(args.forms or ()),
        "roles": tuple(args.roles or ("primary",)),
        "operation": args.operation,
    }


def _engine_taken(args: argparse.Namespace) -> str:
    if args.file:
        return "pipeline"
    if args.mode == "snapshot":
        return "snapshot"
    roles = tuple(args.roles or ("primary",))
    if args.mode == "fast" and roles == ("primary",) and not args.accessions:
        return "fast"
    return "pipeline"


def _summary_payload(
    results: FilingsResult, args: argparse.Namespace
) -> dict[str, object]:
    payload: dict[str, object] = {
        "run_id": results.run_id,
        "plan_id": results.plan_id,
        "accession_count": len(results),
        "engine": _engine_taken(args),
    }
    if payload["engine"] == "snapshot":
        payload["snapshot"] = args.snapshot
    return payload


def _render_summary(results: FilingsResult, args: argparse.Namespace) -> None:
    engine = _engine_taken(args)
    total = len(results)
    print(f"Acquired {total} accessions into run {results.run_id}")
    print(f"Plan: {results.plan_id}")
    print(f"Engine: {engine}")
    if engine == "snapshot":
        print(f"Snapshot: {args.snapshot}")
    table = results.to_arrow()
    shown = min(total, _MAX_GRID_ROWS)
    print(f"Showing {shown} of {total} accessions")
    if total == 0:
        return
    columns = list(table.column_names)
    print(" | ".join(columns))
    for row in table.slice(0, shown).to_pylist():
        print(" | ".join(str(row.get(column, "")) for column in columns))
    if total > shown:
        print(f"... and {total - shown} more (not shown)")


def main(argv: list[str] | None = None) -> int:
    """Run the fetch CLI and return its exit code."""
    args = build_parser().parse_args(argv)
    edgar = Edgar()
    try:
        if args.file:
            results = edgar.fetch_from_file(**_file_kwargs(args))
        else:
            results = edgar.fetch(**_fetch_kwargs(args))
    except (DocumentPlanningError, ProfileResolutionError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.json_output:
        print(json.dumps(_summary_payload(results, args), indent=2))
    else:
        _render_summary(results, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
