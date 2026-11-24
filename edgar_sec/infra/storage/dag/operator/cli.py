"""Unified command-line interface for the snapshot DAG engine.

Provides inspection, lineage traversal, checkout, diagnostics, and garbage collection.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
from collections.abc import Sequence

from ..spec import RelationSpec
from .inspection import cmd_log, cmd_status
from .maintenance import cmd_compact, cmd_doctor, cmd_gc
from .pointers import cmd_checkout, cmd_publish
from .refs import cmd_branch, cmd_tag


def configure_dag_subcommands(
    sub: argparse._SubParsersAction,
    *,
    default_root: Path | Callable[[], Path] | None = None,
    default_specs: Sequence[RelationSpec]
    | Callable[[], Sequence[RelationSpec]]
    | None = None,
) -> None:
    """Configure common DAG subcommands on a subparser action."""
    status_p = sub.add_parser("status", help="Show current snapshot status")
    status_p.add_argument("--branch", default=None, help="Target branch name")

    log_p = sub.add_parser("log", help="Display lineage history")
    log_p.add_argument("-n", "--limit", type=int, default=None, help="Max entries")
    log_p.add_argument("--branch", default=None, help="Target branch name")
    log_p.add_argument("--graph", action="store_true", help="Render ASCII swimlanes")
    log_p.add_argument(
        "--all", action="store_true", help="Include all branch and tag heads"
    )

    pub_p = sub.add_parser("publish", help="Publish a staged snapshot node")
    pub_p.add_argument("staged_dir", type=Path, help="Staged directory to publish")
    pub_p.add_argument(
        "--expected-parent", default=None, help="Expected parent snapshot ID"
    )
    pub_p.add_argument(
        "--allow-null", action="store_true", help="Allow publishing genesis node"
    )
    pub_p.add_argument("--branch", default=None, help="Branch name to publish to")

    br_p = sub.add_parser("branch", help="List, create, or delete branches")
    br_p.add_argument(
        "action",
        nargs="?",
        default="list",
        choices=["list", "create", "delete"],
        help="Branch action",
    )
    br_p.add_argument("name", nargs="?", default=None, help="Branch name")
    br_p.add_argument("--from", dest="from_id", default=None, help="Source snapshot ID")

    tag_p = sub.add_parser("tag", help="List, create, or delete tags")
    tag_p.add_argument(
        "action",
        nargs="?",
        default="list",
        choices=["list", "create", "delete"],
        help="Tag action",
    )
    tag_p.add_argument("name", nargs="?", default=None, help="Tag name")
    tag_p.add_argument("target", nargs="?", default=None, help="Target snapshot ID")
    tag_p.add_argument("-m", "--message", default="", help="Tag message annotation")

    co_p = sub.add_parser("checkout", help="Switch current or branch pointer")
    co_p.add_argument("target", help="Target snapshot ID, branch, or tag")
    co_p.add_argument("--branch", default=None, help="Target branch to switch")
    co_p.add_argument(
        "--force", action="store_true", help="Override lineage affinity guard"
    )

    doc_p = sub.add_parser("doctor", help="Run integrity checks")
    doc_p.add_argument(
        "--skip-digests", action="store_true", help="Skip SHA-256 digest checks"
    )

    if default_specs is not None:
        cmp_p = sub.add_parser("compact", help="Consolidate lineage into a checkpoint")
        cmp_p.add_argument("--branch", default=None, help="Branch to compact")
        cmp_p.add_argument("--new-id", default=None, help="New checkpoint snapshot ID")
        cmp_p.add_argument(
            "--no-publish", action="store_true", help="Do not advance current pointer"
        )

    gc_p = sub.add_parser("gc", help="Collect unreferenced snapshots and parts")
    gc_p.add_argument("--dry-run", action="store_true", help="Preview deletions")


def attach_dag_subparser(
    subparsers: argparse._SubParsersAction,
    *,
    subcommand_name: str = "dag",
    help_text: str = "Snapshot DAG operations",
    default_root: Path | Callable[[], Path] | None = None,
    default_specs: Sequence[RelationSpec]
    | Callable[[], Sequence[RelationSpec]]
    | None = None,
) -> argparse.ArgumentParser:
    """Attach DAG subparser tree with pre-bound defaults for pipeline CLIs."""
    dag_parser = subparsers.add_parser(subcommand_name, help=help_text)
    dag_parser.add_argument(
        "--root", type=Path, default=None, help="Snapshots directory"
    )
    dag_parser.add_argument("--json", action="store_true", help="Format output as JSON")
    sub = dag_parser.add_subparsers(dest="subcommand", required=True)
    configure_dag_subcommands(
        sub, default_root=default_root, default_specs=default_specs
    )
    return dag_parser


def dispatch_dag_subcommand(
    args: argparse.Namespace,
    *,
    default_root: Path | Callable[[], Path] | None = None,
    default_specs: Sequence[RelationSpec]
    | Callable[[], Sequence[RelationSpec]]
    | None = None,
) -> int:
    """Execute parsed DAG subcommand options against resolved root."""
    if getattr(args, "root", None) is not None:
        root = args.root.resolve()
    elif callable(default_root):
        root = default_root().resolve()
    elif default_root is not None:
        root = Path(default_root).resolve()
    else:
        root = Path(".").resolve()

    as_json = bool(getattr(args, "json", False))
    sub = getattr(args, "subcommand", None)

    if sub == "status":
        return cmd_status(root, branch_name=args.branch, as_json=as_json)
    if sub == "log":
        return cmd_log(
            root,
            branch_name=args.branch,
            limit=args.limit,
            graph=args.graph,
            all_heads=args.all,
            as_json=as_json,
        )
    if sub == "publish":
        return cmd_publish(
            root,
            args.staged_dir.resolve(),
            expected_parent_id=args.expected_parent,
            branch_name=args.branch,
            allow_null=args.allow_null,
            as_json=as_json,
        )
    if sub == "branch":
        return cmd_branch(
            root,
            action=args.action,
            name=args.name,
            from_snapshot_id=args.from_id,
            as_json=as_json,
        )
    if sub == "tag":
        return cmd_tag(
            root,
            action=args.action,
            name=args.name,
            target=args.target,
            message=args.message,
            as_json=as_json,
        )
    if sub == "checkout":
        return cmd_checkout(
            root, args.target, branch_name=args.branch, force=args.force
        )
    if sub == "doctor":
        return cmd_doctor(root, verify_digests=not args.skip_digests, as_json=as_json)
    if sub == "compact":
        specs = default_specs() if callable(default_specs) else default_specs
        return cmd_compact(
            root,
            branch_name=args.branch,
            specs=specs,
            new_snapshot_id=args.new_id,
            publish=not args.no_publish,
            as_json=as_json,
        )
    if sub == "gc":
        return cmd_gc(root, dry_run=args.dry_run, as_json=as_json)
    return 1


def build_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser for DAG operations."""
    parser = argparse.ArgumentParser(prog="dag", description="Snapshot DAG CLI")
    parser.add_argument(
        "--root", type=Path, default=Path("."), help="Snapshots directory"
    )
    parser.add_argument("--json", action="store_true", help="Format output as JSON")
    sub = parser.add_subparsers(dest="subcommand", required=True)
    configure_dag_subcommands(sub)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for DAG CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return dispatch_dag_subcommand(args)


__all__ = [
    "attach_dag_subparser",
    "build_parser",
    "configure_dag_subcommands",
    "dispatch_dag_subcommand",
    "main",
]


if __name__ == "__main__":
    sys.exit(main())
