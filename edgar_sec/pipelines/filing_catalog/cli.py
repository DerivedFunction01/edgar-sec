"""Command surface for the filing-catalog pipeline.

``materialize`` turns a finalized metadata snapshot into an immutable catalog;
``plan`` slices it into a target plan; ``expand`` scales a policy plan while
retaining its parent's locators. Nothing here performs network work.
"""

from __future__ import annotations

import argparse
import sys

from edgar_sec.foundation.runtime.settings.validators import positive_int_type
from edgar_sec.infra.storage.dag.cli import (
    attach_dag_subparser,
    dispatch_dag_subcommand,
)
from edgar_sec.pipelines.filing_catalog.paths import (
    resolve_filing_catalog_paths,
)
from edgar_sec.pipelines.filing_catalog.planner import (
    SCOPE_DETERMINISTIC,
    SCOPE_POLICY,
)
from edgar_sec.pipelines.filing_catalog.specs import CATALOG_RELATION_SPECS

from .commands.common import resolve_artifacts
from .commands.expand import cmd_expand
from .commands.materialize import cmd_materialize
from .commands.plan import cmd_plan
from .commands.status import cmd_status

__all__ = [
    "build_parser",
    "main",
]


def build_parser() -> argparse.ArgumentParser:
    """Build the filing catalog argument parser."""
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
        "--source-snapshot",
        default="",
        help="Phase 1 snapshot id recorded in its DAG catalog",
    )
    materialize_parser.add_argument(
        "--source-artifacts",
        default="",
        help="Artifact root containing the Phase 1 snapshot DAG catalog",
    )
    materialize_parser.add_argument(
        "--artifacts", default="", help="artifacts root override"
    )
    materialize_parser.add_argument(
        "--branch",
        default="main",
        help="DAG branch to advance on durable publication (default: main)",
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
    plan_parser.add_argument(
        "--cohort",
        default="",
        help="restrict deterministic targets to a cohort id or name",
    )
    plan_parser.add_argument(
        "--seed-cohort",
        default="",
        help="use a cohort's CIKs as policy seeds (policy scope)",
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
        "status", help="report published catalogs and plans from the DAG catalog"
    )
    status_parser.add_argument(
        "--artifacts", default="", help="artifacts root override"
    )
    status_parser.set_defaults(func=cmd_status)

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
                    resolve_artifacts(getattr(args, "artifacts", ""))
                ).snapshots_root
            ),
            default_specs=CATALOG_RELATION_SPECS,
        )
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    args = sys.argv[1:] if argv is None else argv
    parser = build_parser()
    parsed = parser.parse_args(args)
    return int(parsed.func(parsed))


if __name__ == "__main__":
    sys.exit(main())
