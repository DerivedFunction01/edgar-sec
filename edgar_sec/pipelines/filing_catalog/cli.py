"""Command surface for the filing-catalog pipeline.
``materialize`` turns a finalized metadata snapshot into an immutable catalog;
``plan`` slices it into a target plan; ``expand`` scales a policy plan while
retaining its parent's locators. Nothing here performs network work.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from edgar_sec.engine.selection.policy import SelectionPolicy
from edgar_sec.foundation.runtime.settings.validators import positive_int_type
from edgar_sec.pipelines.filing_catalog.catalog_job import (
    CatalogError,
    materialize,
)
from edgar_sec.pipelines.filing_catalog.discovery import auto_policy
from edgar_sec.pipelines.filing_catalog.discovery import status as build_status
from edgar_sec.pipelines.filing_catalog.expansion import ParentPlanError, expand
from edgar_sec.pipelines.filing_catalog.paths import resolve_filing_catalog_paths
from edgar_sec.pipelines.filing_catalog.planner import SCOPE_DETERMINISTIC, SCOPE_POLICY
from edgar_sec.pipelines.filing_catalog.planner import plan as build_plan
from edgar_sec.pipelines.filing_catalog.planner import plan_policy as build_policy_plan
from edgar_sec.pipelines.filing_catalog.publication import PlanConflictError

__all__ = ["build_parser", "main"]


def _emit_progress(event: dict[str, Any]) -> None:
    """Write progress to stderr so stdout carries only the JSON result.

    Mixing a human-readable trace into stdout would corrupt ``... | jq``.
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
            progress=_emit_progress,
        )
    except CatalogError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    artifacts = _resolve_artifacts(args.artifacts)
    try:
        if args.scope == SCOPE_POLICY:
            policy = _load_policy(args)
            plan = build_policy_plan(
                args.catalog, policy, artifacts, progress=_emit_progress
            )
        else:
            plan = build_plan(
                args.catalog,
                artifacts,
                forms=tuple(args.forms) if args.forms else None,
                document_suffixes=tuple(args.suffixes) if args.suffixes else None,
                dates=args.dates,
                limit=args.limit,
                progress=_emit_progress,
            )
    except (PlanConflictError, ValueError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(plan, indent=2, sort_keys=True))
    return 0


def _load_policy(args: argparse.Namespace) -> SelectionPolicy:
    """Resolve the policy for ``plan --scope policy``.
    Neither ``--policy`` nor ``--auto-policy`` is an error rather than a silent default:
    an assumed quota profile is indistinguishable from a deliberate one.
    """
    if args.policy and args.auto_policy:
        raise ValueError("pass either --policy or --auto-policy, not both")
    if args.policy:
        return SelectionPolicy.from_path(args.policy)
    if args.auto_policy:
        return auto_policy(args.catalog, _resolve_artifacts(args.artifacts))
    raise ValueError("--scope policy requires --policy PATH or --auto-policy")


def cmd_expand(args: argparse.Namespace) -> int:
    try:
        plan = expand(
            args.parent_plan,
            args.target_units,
            artifacts_root=_resolve_artifacts(args.artifacts),
            progress=_emit_progress,
        )
    except (PlanConflictError, ParentPlanError, ValueError, OSError) as error:
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
    materialize_parser.set_defaults(func=cmd_materialize)

    plan_parser = subparsers.add_parser(
        "plan", help="publish a deterministic or policy-driven target plan"
    )
    plan_parser.add_argument("--catalog", required=True, help="catalog id or 'current'")
    plan_parser.add_argument(
        "--scope",
        default=SCOPE_DETERMINISTIC,
        choices=[SCOPE_DETERMINISTIC, SCOPE_POLICY],
        help="deterministic target filtering; policy fills a quota profile",
    )
    plan_parser.add_argument(
        "--policy", default="", help="selection policy document (policy scope)"
    )
    plan_parser.add_argument(
        "--auto-policy",
        action="store_true",
        help="derive a baseline policy from the catalog (policy scope)",
    )
    plan_parser.add_argument("--artifacts", default="", help="artifacts root override")
    plan_parser.add_argument(
        "--forms", nargs="*", default=[], help="restrict to these form types"
    )
    plan_parser.add_argument(
        "--suffixes",
        nargs="*",
        default=[],
        help="allowed document suffixes, e.g. .htm .txt",
    )
    plan_parser.add_argument(
        "--dates",
        default="",
        metavar="SELECTION",
        help=(
            "report_date selection as one comma-separated union of absolute "
            "intervals and recurring periods, e.g. "
            "'@Q1[1999..2001],2005Q3..2008Q1,2011-12-31..2019-11-03'. "
            "Atoms: YYYY, YYYYQn, YYYY-MM, YYYY-MM-DD; ranges use '..' and may "
            "be open on either side. Recurring: @Q1-@Q4, @M01-@M12, each with "
            "optional inclusive years '@Q1[2011..2015]'. Blank selects every date"
        ),
    )
    plan_parser.add_argument(
        "--limit",
        type=positive_int_type,
        default=None,
        help="max rows per form partition",
    )
    plan_parser.set_defaults(func=cmd_plan)

    expand_parser = subparsers.add_parser(
        "expand",
        help="scale a policy plan while retaining every parent locator",
    )
    expand_parser.add_argument(
        "--parent-plan", required=True, help="published policy plan directory"
    )
    expand_parser.add_argument(
        "--target-units",
        type=positive_int_type,
        required=True,
        help="child plan locator target",
    )
    expand_parser.add_argument(
        "--artifacts", default="", help="artifacts root override"
    )
    expand_parser.set_defaults(func=cmd_expand)

    status_parser = subparsers.add_parser(
        "status", help="report published catalogs and plans from manifests"
    )
    status_parser.add_argument(
        "--artifacts", default="", help="artifacts root override"
    )
    status_parser.set_defaults(func=cmd_status)

    from edgar_sec.infra.storage.dag.cli import (
        attach_dag_subparser,
        dispatch_dag_subcommand,
    )
    from .specs import CATALOG_RELATION_SPECS

    dag_parser = attach_dag_subparser(
        subparsers,
        subcommand_name="dag",
        default_root=lambda: resolve_filing_catalog_paths().snapshots_root,
        default_specs=CATALOG_RELATION_SPECS,
    )
    dag_parser.set_defaults(
        func=lambda args: dispatch_dag_subcommand(
            args,
            default_root=lambda: (
                resolve_filing_catalog_paths(
                    _resolve_artifacts(getattr(args, "artifacts", ""))
                ).snapshots_root
            ),
            default_specs=CATALOG_RELATION_SPECS,
        )
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    parsed = parser.parse_args(args)
    return int(parsed.func(parsed))
