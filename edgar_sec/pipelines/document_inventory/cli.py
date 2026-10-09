"""Command surface for document inventory fixture and review operations."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from edgar_sec.foundation.runtime.settings.validators import positive_int_type
from edgar_sec.infra.storage.dag.cli import (
    attach_dag_subparser,
    dispatch_dag_subcommand,
)
from edgar_sec.pipelines.document_inventory.paths import InventoryPaths
from edgar_sec.pipelines.document_inventory.snapshot.specs import (
    INVENTORY_RELATIONS,
)

from .commands.build import cmd_build
from .commands.common import (
    resolve_artifacts_root as _artifacts_root,
)
from .commands.fixture import (
    cmd_fixture_create,
    cmd_fixture_fill,
    cmd_fixture_list,
)
from .commands.query import cmd_query
from .commands.review import cmd_review_artifacts

__all__ = [
    "build_parser",
    "main",
]


def _add_output_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--artifacts",
        dest="artifacts_root",
        default="",
        help="artifacts root override",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON to stdout")


def build_parser() -> argparse.ArgumentParser:
    """Build the document inventory command line argument parser."""
    parser = argparse.ArgumentParser(
        prog="inventory",
        description="Capture and review SEC filing index pages.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    build_cmd = commands.add_parser(
        "build", help="build and publish an immutable inventory snapshot"
    )
    build_cmd.add_argument("--catalog-plan", required=True, help="published plan id")
    build_cmd.add_argument(
        "--base-snapshot-id", default=None, help="base snapshot id override"
    )
    build_cmd.add_argument(
        "--branch",
        default="main",
        help="DAG branch to advance on publication (default: main)",
    )
    build_cmd.add_argument(
        "--explicit-refresh",
        action="store_true",
        help="force re-fetch of index pages",
    )
    build_cmd.add_argument(
        "--chunk-size", type=positive_int_type, help="accessions per S4 chunk"
    )
    build_cmd.add_argument(
        "--retry-failures",
        action="store_true",
        help="retry failed chunk attempts",
    )
    build_cmd.add_argument(
        "--workers", type=positive_int_type, help="worker process count"
    )
    _add_output_options(build_cmd)
    build_cmd.set_defaults(func=cmd_build)

    query_cmd = commands.add_parser(
        "query", help="query active document inventory snapshots"
    )
    query_cmd.add_argument("--accession", help="exact accession number")
    query_cmd.add_argument("--form", help="filing form filter")
    query_cmd.add_argument("--filing-cik", help="canonical filing CIK filter")
    query_cmd.add_argument("--source-cik", help="discovery source CIK filter")
    query_cmd.add_argument("--limit", type=positive_int_type, help="limit results")
    _add_output_options(query_cmd)
    query_cmd.set_defaults(func=cmd_query)

    from edgar_sec.infra.storage.review.cli import attach_review_subparsers
    from .review_adapter import InventoryReviewAdapter

    attach_review_subparsers(commands, InventoryReviewAdapter())

    dag_parser = attach_dag_subparser(
        commands,
        subcommand_name="dag",
        default_root=lambda: InventoryPaths(_artifacts_root(None)).snapshots_root,
        default_specs=INVENTORY_RELATIONS,
    )
    dag_parser.set_defaults(
        func=lambda args: dispatch_dag_subcommand(
            args,
            default_root=lambda: (
                InventoryPaths(
                    _artifacts_root(getattr(args, "artifacts_root", None))
                ).snapshots_root
            ),
            default_specs=INVENTORY_RELATIONS,
        )
    )

    from edgar_sec.infra.distribution.cli import attach_distrib_subparser
    from .distribution_adapter import InventoryDistributionAdapter

    attach_distrib_subparser(
        commands,
        lambda args: InventoryDistributionAdapter(
            artifacts_root=Path(args.artifacts_root).resolve()
            if getattr(args, "artifacts_root", None)
            else None
        ),
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    if argv is None and len(sys.argv) == 1:
        build_parser().print_help()
        return 0
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
