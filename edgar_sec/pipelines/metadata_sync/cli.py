"""Unified command surface for the metadata sync pipeline.

Every command is a plain callable over one typed options model, so the operator
and the CLI are one code path.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from edgar_sec.foundation.runtime.settings.validators import (
    non_negative_int_type,
    positive_int_type,
)
from edgar_sec.infra.storage.dag.cli import (
    attach_dag_subparser,
    dispatch_dag_subcommand,
)

from edgar_sec.infra.distribution.cli import attach_distrib_subparser

from .assignment import AssignmentError
from .commands.augment import cmd_augment
from .commands.merge import cmd_merge
from .commands.plan import cmd_plan, cmd_status
from .commands.run import cmd_run
from .distribution_adapter import MetadataDistributionAdapter
from .options import (
    PlanOptions,
    RunOptions,
    plan_options,
    run_options,
)
from .paths import resolve_metadata_paths
from .roster import RosterError
from .sec_client import SubmissionsClient
from .specs import METADATA_RELATION_SPECS

__all__ = [
    "build_parser",
    "main",
]


# ------------------------------------------------------------------- argparse


def _add_common(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--artifacts", default="", help="artifacts root override")
    sub.add_argument(
        "--chunk-size",
        type=positive_int_type,
        default=None,
        help="CIKs per resumable chunk; defaults to runtime.chunk_size",
    )
    sub.add_argument(
        "--workers",
        type=positive_int_type,
        default=None,
        help="worker threads; machine-derived if unset",
    )


def _add_branch_guard(sub: argparse.ArgumentParser) -> None:
    """Attach the shared DAG branch and expected-tip publication guard."""
    sub.add_argument(
        "--branch",
        default="main",
        help="DAG branch to advance (default: main)",
    )
    sub.add_argument(
        "--expected-branch-tip",
        default=None,
        help="snapshot id the branch tip must still name; defaults to the tip "
        "observed when the command starts",
    )


def _add_plan_reference(sub: argparse.ArgumentParser) -> None:
    """Attach an explicit plan, bundle, or published cohort reference."""
    group = sub.add_mutually_exclusive_group()
    group.add_argument("--plan-id", default="", help="plan identifier to operate on")
    group.add_argument("--bundle", default="", help="copied plan bundle directory")
    group.add_argument("--cohort", default="", help="published cohort name or id")


def _add_cohort_source(sub: argparse.ArgumentParser, *, with_limit: bool) -> None:
    """Attach the sole dataset selector used for planning or augmentation."""
    sub.add_argument("--cohort", required=True, help="published cohort name or id")
    if with_limit:
        sub.add_argument("--limit", type=positive_int_type, default=None)


def _add_chunk_selection(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--chunks", default="", help="chunk ids or ranges, e.g. '0-3,7'")
    sub.add_argument(
        "--chunk", type=non_negative_int_type, default=None, help="a single chunk id"
    )


def _plan_options(args: argparse.Namespace) -> PlanOptions:
    return plan_options(
        cohort=args.cohort,
        artifacts_root=args.artifacts or None,
        chunk_size=args.chunk_size,
        limit=getattr(args, "limit", None),
    )


def _run_options(args: argparse.Namespace) -> RunOptions:
    return run_options(
        plan_id=getattr(args, "plan_id", "") or "",
        cohort=args.cohort or "",
        chunk_size=args.chunk_size,
        limit=getattr(args, "limit", None),
        artifacts_root=args.artifacts or None,
        bundle_root=getattr(args, "bundle", "") or None,
        worker_id=getattr(args, "worker", "") or "",
        chunk_ids=_chunk_selection(args),
        workers=args.workers,
        branch_name=getattr(args, "branch", "main") or "main",
        expected_branch_tip=getattr(args, "expected_branch_tip", None),
    )


def _chunk_selection(args: argparse.Namespace) -> tuple[int, ...]:
    selected: list[int] = []
    spec = getattr(args, "chunks", "")
    if spec:
        from edgar_sec.foundation.runtime.partitions import parse_id_selection

        selected.extend(parse_id_selection(spec))
    single = getattr(args, "chunk", None)
    if single is not None:
        selected.append(single)
    return tuple(sorted(set(selected)))


def _require(value: str, flag: str) -> str:
    if not value:
        raise ValueError(f"{flag} is required")
    return value


def build_parser() -> argparse.ArgumentParser:
    """Build the metadata sync argument parser."""
    parser = argparse.ArgumentParser(
        prog="metadata", description="SEC submissions metadata sync pipeline"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan", help="generate a deterministic plan")
    _add_cohort_source(plan_parser, with_limit=True)
    _add_common(plan_parser)
    plan_parser.set_defaults(func=lambda args: cmd_plan(_plan_options(args)))

    status_parser = subparsers.add_parser("status", help="report plan progress")
    _add_plan_reference(status_parser)
    _add_common(status_parser)
    status_parser.set_defaults(func=lambda args: cmd_status(_run_options(args)))

    run_parser = subparsers.add_parser("run", help="execute resumable chunks")
    _add_plan_reference(run_parser)
    _add_common(run_parser)
    _add_chunk_selection(run_parser)
    run_parser.set_defaults(func=lambda args: cmd_run(_run_options(args)))

    merge_parser = subparsers.add_parser("merge", help="publish a snapshot")
    _add_plan_reference(merge_parser)
    _add_common(merge_parser)
    _add_branch_guard(merge_parser)
    merge_parser.set_defaults(func=lambda args: cmd_merge(_run_options(args)))

    attach_distrib_subparser(
        subparsers,
        lambda args: MetadataDistributionAdapter(
            artifacts_root=Path(args.artifacts).resolve()
            if getattr(args, "artifacts", None)
            else None
        ),
    )

    augment_parser = subparsers.add_parser(
        "augment", help="add new CIKs to a published snapshot"
    )
    _add_cohort_source(augment_parser, with_limit=False)
    _add_common(augment_parser)
    _add_branch_guard(augment_parser)
    augment_parser.add_argument("--base-snapshot-id", required=True)
    augment_parser.add_argument(
        "--new-snapshot-id",
        default="",
        help=(
            "snapshot id to publish under; defaults to the derived delta plan id, "
            "which is content-addressed over the base snapshot and delta cohort"
        ),
    )
    augment_parser.set_defaults(func=lambda args: _augment_from_args(args))

    dag_parser = attach_dag_subparser(
        subparsers,
        subcommand_name="dag",
        default_root=lambda: resolve_metadata_paths().snapshots_root,
        default_specs=METADATA_RELATION_SPECS,
    )
    dag_parser.set_defaults(
        func=lambda args: dispatch_dag_subcommand(
            args,
            default_root=lambda: resolve_metadata_paths().snapshots_root,
            default_specs=METADATA_RELATION_SPECS,
        )
    )

    return parser


def _augment_from_args(args: argparse.Namespace) -> int:
    options = plan_options(
        cohort=args.cohort,
        artifacts_root=args.artifacts or None,
        chunk_size=args.chunk_size,
    )
    return cmd_augment(
        options,
        base_snapshot_id=args.base_snapshot_id,
        new_snapshot_id=args.new_snapshot_id,
        workers=args.workers,
        branch_name=getattr(args, "branch", "main") or "main",
        expected_branch_tip=getattr(args, "expected_branch_tip", None),
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except (
        AssignmentError,
        FileNotFoundError,
        RosterError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
