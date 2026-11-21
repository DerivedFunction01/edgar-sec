"""Unified command surface for the datasets pipeline.

Every command is a plain callable over one typed options model, so the
operator and the CLI are one code path.
"""

from __future__ import annotations

import argparse
import sys

from edgar_sec.infra.storage.dag.cli import (
    attach_dag_subparser,
    dispatch_dag_subcommand,
)

from .commands.import_set import cmd_import
from .commands.population import cmd_population
from .commands.publish import cmd_publish
from .commands.status import cmd_status
from .commands.verify import cmd_verify
from .options import DatasetsOptions, datasets_options
from .paths import resolve_datasets_paths
from .specs import DATASET_RELATION_SPECS, DATASET_SPECS

__all__ = ["build_parser", "main"]


def _add_common(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--artifacts", default="", help="artifacts root override")
    sub.add_argument(
        "--branch", default="main", help="DAG branch to advance (default: main)"
    )


def _options(args: argparse.Namespace) -> DatasetsOptions:
    return datasets_options(
        artifacts_root=args.artifacts or None,
        branch=getattr(args, "branch", "main") or "main",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the datasets argument parser."""
    parser = argparse.ArgumentParser(
        prog="datasets",
        description="SEC data-research dataset imports (oracle posture)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser(
        "import", help="download and load vintages of one dataset set"
    )
    _add_common(import_parser)
    import_parser.add_argument(
        "--set", required=True, choices=sorted(DATASET_SPECS), help="dataset set id"
    )
    import_parser.add_argument(
        "--vintage",
        action="append",
        required=True,
        help="vintage label as listed by SEC (repeatable)",
    )
    import_parser.set_defaults(
        func=lambda args: cmd_import(
            _options(args), set_id=args.set, vintages=tuple(args.vintage)
        )
    )

    population_parser = subparsers.add_parser(
        "population", help="load the BDC Report population register"
    )
    _add_common(population_parser)
    population_parser.add_argument(
        "--year",
        action="append",
        type=int,
        default=None,
        help="report year (repeatable; default: latest three years)",
    )
    population_parser.set_defaults(
        func=lambda args: cmd_population(
            _options(args), years=tuple(args.year) if args.year else None
        )
    )

    publish_parser = subparsers.add_parser(
        "publish", help="publish the store index as the next DAG snapshot"
    )
    _add_common(publish_parser)
    publish_parser.set_defaults(func=lambda args: cmd_publish(_options(args)))

    verify_parser = subparsers.add_parser(
        "verify", help="run the oracle verification pass over the store"
    )
    _add_common(verify_parser)
    verify_parser.set_defaults(func=lambda args: cmd_verify(_options(args)))

    status_parser = subparsers.add_parser(
        "status", help="report the store's vintages and the index tip"
    )
    _add_common(status_parser)
    status_parser.set_defaults(func=lambda args: cmd_status(_options(args)))

    dag_parser = attach_dag_subparser(
        subparsers,
        subcommand_name="dag",
        default_root=lambda: resolve_datasets_paths().snapshots_root,
        default_specs=DATASET_RELATION_SPECS,
    )
    dag_parser.set_defaults(
        func=lambda args: dispatch_dag_subcommand(
            args,
            default_root=lambda: resolve_datasets_paths().snapshots_root,
            default_specs=DATASET_RELATION_SPECS,
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
