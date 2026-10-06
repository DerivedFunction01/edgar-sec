"""Command surface for the document_inventory pipeline.

Subcommands are placeholders on the stable CLI contract while the owning stages
are implemented; every command body fails closed rather than faking behavior.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from edgar_sec.foundation.runtime.paths import ProjectPaths, resolve_paths

__all__ = ["build_parser", "main"]


@dataclass(frozen=True, slots=True)
class _CommonOptions:
    """Shared options for most document_inventory commands."""

    artifacts: Path | None
    workers: int | None
    json: bool
    limit: int | None


def _add_common(sub: argparse.ArgumentParser) -> None:
    """Attach shared options used by most document_inventory commands."""
    sub.add_argument("--artifacts", default="", help="artifacts root override")
    sub.add_argument(
        "--workers",
        type=int,
        default=None,
        help="explicit worker count; machine-derived if absent",
    )
    sub.add_argument(
        "--limit",
        type=int,
        default=None,
        help="cap for a smoke run",
    )
    sub.add_argument(
        "--json",
        action="store_true",
        help="emit the result as JSON on stdout",
    )


def _resolve_common(args: argparse.Namespace) -> _CommonOptions:
    return _CommonOptions(
        artifacts=Path(args.artifacts).resolve() if args.artifacts else None,
        workers=args.workers,
        json=args.json,
        limit=getattr(args, "limit", None),
    )


def _paths_from(options: _CommonOptions) -> ProjectPaths:
    return resolve_paths(options.artifacts)


def _cmd_cohort(options: _CommonOptions, paths: ProjectPaths) -> int:
    raise NotImplementedError("not implemented")


def _cmd_index_list(options: _CommonOptions, paths: ProjectPaths) -> int:
    raise NotImplementedError("index list is not implemented")


def _cmd_index_replay(options: _CommonOptions, paths: ProjectPaths) -> int:
    raise NotImplementedError("index replay is not implemented")


def _cmd_status(options: _CommonOptions, paths: ProjectPaths) -> int:
    raise NotImplementedError("status is not implemented")


def _cmd_query(options: _CommonOptions, paths: ProjectPaths) -> int:
    raise NotImplementedError("query is not implemented")


def _cmd_publish(options: _CommonOptions, paths: ProjectPaths) -> int:
    raise NotImplementedError("publish is not implemented")


_COMMANDS = {
    "cohort": _cmd_cohort,
    "index-list": _cmd_index_list,
    "index-replay": _cmd_index_replay,
    "status": _cmd_status,
    "query": _cmd_query,
    "publish": _cmd_publish,
}

USAGE_EPILOG = """\
examples:
  python run.py inventory cohort --input cohort.parquet
  python run.py inventory index list
  python run.py inventory index replay --accession 0000123456-12-000001
  python run.py inventory status
  python run.py inventory query --form 10-K
  python run.py inventory publish
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="inventory",
        description="Document inventory: cohort, index pages, snapshot.",
        epilog=USAGE_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    cohort_parser = sub.add_parser("cohort", help="build the inventory cohort")
    cohort_parser.add_argument("--input", default="", help="cohort source")
    _add_common(cohort_parser)
    cohort_parser.set_defaults(func=_cmd_cohort)

    index = sub.add_parser("index", help="index-page operations")
    index_sub = index.add_subparsers(dest="index_command", required=True)

    index_list = index_sub.add_parser("list", help="list captured index pages")
    _add_common(index_list)
    index_list.set_defaults(func=_cmd_index_list)

    index_replay = index_sub.add_parser("replay", help="replay a captured page")
    index_replay.add_argument(
        "--accession",
        default="",
        help="accession whose page to replay",
    )
    index_replay.add_argument("--url", default="", help="request URL")
    _add_common(index_replay)
    index_replay.set_defaults(func=_cmd_index_replay)

    status_parser = sub.add_parser("status", help="report the inventory snapshot")
    _add_common(status_parser)
    status_parser.set_defaults(func=_cmd_status)

    query_parser = sub.add_parser("query", help="query the snapshot")
    query_parser.add_argument("--form", default="", help="form type filter")
    query_parser.add_argument("--accession", default="", help="accession filter")
    _add_common(query_parser)
    query_parser.set_defaults(func=_cmd_query)

    publish_parser = sub.add_parser("publish", help="publish the inventory snapshot")
    _add_common(publish_parser)
    publish_parser.set_defaults(func=_cmd_publish)

    return parser


def _interactive(paths: ProjectPaths) -> int:
    """Narrow interactive menu used by the root launcher."""
    commands: dict[str, Callable[[_CommonOptions, ProjectPaths], int]] = {
        "1": _cmd_cohort,
        "2": _cmd_index_list,
        "3": _cmd_index_replay,
        "4": _cmd_status,
        "5": _cmd_query,
        "6": _cmd_publish,
    }
    while True:
        print("\nDocument Inventory")
        print("  1. Build the cohort from a source")
        print("  2. List captured index pages")
        print("  3. Replay a captured index page")
        print("  4. Report snapshot status")
        print("  5. Query the snapshot")
        print("  6. Publish the snapshot")
        print("  0. Exit")
        try:
            choice = input("Choice [0]: ").strip()
        except EOFError:
            return 0
        if not choice or choice == "0":
            return 0
        handler = commands.get(choice)
        if handler is None:
            print("Invalid choice, please select again.")
            continue
        try:
            handler(_CommonOptions(None, None, False, None), paths)
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            continue
        continue


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``python run.py inventory ...``."""
    if argv is None and len(sys.argv) == 1:
        return _interactive(resolve_paths())
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    paths = _paths_from(_resolve_common(args))
    try:
        return int(args.func(_resolve_common(args), paths))
    except KeyboardInterrupt:
        return 130
    except NotImplementedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
