"""CLI subparser bindings for review generation, comparison, and fixtures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from edgar_sec.foundation.runtime.settings.validators import positive_int_type

from .adapter import ReviewAdapter
from .diff import compare_review_runs
from .paths import (
    ReviewPaths,
    new_diff_dir,
    new_review_run_dir,
    review_runs_root,
)


def attach_review_subparsers(
    subparsers: argparse._SubParsersAction,
    adapter: ReviewAdapter,
) -> None:
    """Attach 'review' and 'fixture' subparsers to the parent command parser."""
    _attach_review_commands(subparsers, adapter)
    _attach_fixture_commands(subparsers, adapter)


def _attach_review_commands(
    subparsers: argparse._SubParsersAction,
    adapter: ReviewAdapter,
) -> None:
    review_parser = subparsers.add_parser(
        "review",
        help="generate review artifacts and compare review runs",
    )
    commands = review_parser.add_subparsers(dest="review_command", required=True)

    gen = commands.add_parser("generate", help="render review artifacts from a fixture")
    gen.add_argument("--fixture", required=True, help="fixture id to review")
    gen.add_argument("--output", help="output directory (auto-derived if omitted)")
    gen.add_argument("--limit", type=positive_int_type, help="limit review cases")
    gen.add_argument("--workers", type=positive_int_type, help="worker process count")
    gen.add_argument(
        "--accession",
        action="append",
        dest="accessions",
        help="restrict to accession (repeatable)",
    )
    gen.add_argument("--artifacts", default="", help="artifacts root override")
    gen.add_argument("--json", action="store_true", help="emit JSON output")
    gen.set_defaults(func=lambda args: _cmd_generate(args, adapter))

    cmp_cmd = commands.add_parser(
        "compare", help="compare two review runs and report diffs"
    )
    cmp_cmd.add_argument("--base", required=True, help="base review run directory")
    cmp_cmd.add_argument("--new", required=True, help="new review run directory")
    cmp_cmd.add_argument(
        "--output", help="diff output directory (auto-derived if omitted)"
    )
    cmp_cmd.add_argument(
        "--max-display",
        type=positive_int_type,
        default=20,
        help="maximum changed cases to list in console",
    )
    cmp_cmd.add_argument("--artifacts", default="", help="artifacts root override")
    cmp_cmd.add_argument("--json", action="store_true", help="emit JSON output")
    cmp_cmd.set_defaults(func=lambda args: _cmd_compare(args, adapter))


def _attach_fixture_commands(
    subparsers: argparse._SubParsersAction,
    adapter: ReviewAdapter,
) -> None:
    fixture_parser = subparsers.add_parser(
        "fixture",
        help="create, fill, and list dataset fixtures",
    )
    commands = fixture_parser.add_subparsers(dest="fixture_command", required=True)

    create_cmd = commands.add_parser("create", help="create and capture a new fixture")
    create_cmd.add_argument("--fixture", required=True, help="fixture id")
    create_cmd.add_argument(
        "--catalog-plan", required=True, help="published catalog plan id"
    )
    create_cmd.add_argument(
        "--limit", type=positive_int_type, help="limit target cases"
    )
    create_cmd.add_argument("--artifacts", default="", help="artifacts root override")
    create_cmd.add_argument("--json", action="store_true", help="emit JSON output")
    create_cmd.set_defaults(func=lambda args: _cmd_create_fixture(args, adapter))

    fill_cmd = commands.add_parser("fill", help="extend an existing fixture")
    fill_cmd.add_argument("--fixture", required=True, help="fixture id")
    fill_cmd.add_argument(
        "--catalog-plan", required=True, help="published catalog plan id"
    )
    fill_cmd.add_argument("--limit", type=positive_int_type, help="limit target cases")
    fill_cmd.add_argument("--artifacts", default="", help="artifacts root override")
    fill_cmd.add_argument("--json", action="store_true", help="emit JSON output")
    fill_cmd.set_defaults(func=lambda args: _cmd_fill_fixture(args, adapter))

    list_cmd = commands.add_parser("list", help="list discovered fixtures")
    list_cmd.add_argument("--artifacts", default="", help="artifacts root override")
    list_cmd.add_argument("--json", action="store_true", help="emit JSON output")
    list_cmd.set_defaults(func=lambda args: _cmd_list_fixtures(args, adapter))


def _cmd_generate(args: argparse.Namespace, adapter: ReviewAdapter) -> int:
    output_dir = (
        Path(args.output)
        if args.output
        else _derive_run_dir(args.artifacts, adapter.dataset_name)
    )
    exit_code = adapter.build_review_artifacts(
        fixture_id=args.fixture,
        output_dir=output_dir,
        limit=args.limit,
        workers=args.workers,
        accessions=args.accessions,
        artifacts_root=args.artifacts,
    )
    if not args.json:
        print(f"Review artifacts written to: {output_dir}")
    return exit_code


def _cmd_compare(args: argparse.Namespace, adapter: ReviewAdapter) -> int:
    base_dir = Path(args.base)
    new_dir = Path(args.new)
    output_dir = (
        Path(args.output)
        if args.output
        else _derive_diff_dir(args.artifacts, adapter.dataset_name)
    )
    summary = compare_review_runs(
        base_dir=base_dir,
        new_dir=new_dir,
        output_dir=output_dir,
        adapter=adapter,
        max_display=args.max_display,
    )
    if args.json:
        print(
            json.dumps(
                {
                    "base_run": summary.base_run,
                    "new_run": summary.new_run,
                    "total_cases": summary.total_cases,
                    "unchanged": summary.unchanged_count,
                    "changed": summary.changed_count,
                    "added": summary.added_count,
                    "removed": summary.removed_count,
                    "output_dir": str(output_dir),
                },
                indent=2,
            )
        )
    else:
        print(ReviewPaths(output_dir).summary_file.read_text(encoding="utf-8"))
    return 0


def _cmd_create_fixture(args: argparse.Namespace, adapter: ReviewAdapter) -> int:
    try:
        return adapter.create_fixture(
            fixture_id=args.fixture,
            catalog_plan=args.catalog_plan,
            limit=args.limit,
            artifacts_root=args.artifacts,
            json=getattr(args, "json", False),
        )
    except TypeError:
        return adapter.create_fixture(
            fixture_id=args.fixture,
            catalog_plan=args.catalog_plan,
            limit=args.limit,
            artifacts_root=args.artifacts,
        )


def _cmd_fill_fixture(args: argparse.Namespace, adapter: ReviewAdapter) -> int:
    try:
        return adapter.fill_fixture(
            fixture_id=args.fixture,
            catalog_plan=args.catalog_plan,
            limit=args.limit,
            artifacts_root=args.artifacts,
            json=getattr(args, "json", False),
        )
    except TypeError:
        return adapter.fill_fixture(
            fixture_id=args.fixture,
            catalog_plan=args.catalog_plan,
            limit=args.limit,
            artifacts_root=args.artifacts,
        )


def _cmd_list_fixtures(args: argparse.Namespace, adapter: ReviewAdapter) -> int:
    cmd_fn = getattr(adapter, "cmd_list_fixtures", None)
    if callable(cmd_fn):
        return int(cmd_fn(args))
    fixtures = adapter.list_fixtures(args.artifacts)
    if args.json:
        print(json.dumps(fixtures, indent=2))
    else:
        if not fixtures:
            print("No fixtures found.")
            return 0
        print(f"Discovered {len(fixtures)} fixture(s):")
        for f in fixtures:
            fid = f.get("fixture_id", "unknown")
            cases = f.get("case_count", f.get("total_cases", ""))
            print(f"  * {fid:<24} ({cases} cases)")
    return 0


def _derive_run_dir(artifacts_root: str, dataset: str) -> Path:
    from edgar_sec.foundation.runtime.paths import resolve_paths

    root = Path(artifacts_root) if artifacts_root else resolve_paths().artifacts_root
    return new_review_run_dir(review_runs_root(root, dataset))


def _derive_diff_dir(artifacts_root: str, dataset: str) -> Path:
    from edgar_sec.foundation.runtime.paths import resolve_paths

    root = Path(artifacts_root) if artifacts_root else resolve_paths().artifacts_root
    return new_diff_dir(review_runs_root(root, dataset))
