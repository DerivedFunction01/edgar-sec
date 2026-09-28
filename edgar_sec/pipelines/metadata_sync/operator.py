"""Interactive terminal operator for the metadata sync pipeline.

The wizard is a thin presentation layer: every action delegates to the same
command functions the CLI uses, so the two surfaces cannot drift.
"""

from __future__ import annotations

import argparse
import sys

from edgar_sec.foundation.runtime.interactive import (
    MenuAction,
    operator_entrypoint,
    prompt_text,
)

from .cli import cmd_augment, cmd_merge, cmd_plan, cmd_run, cmd_status
from .cli import main as cli_main

__all__ = ["build_operator_menu", "main"]

MENU_TITLE = "Metadata Sync (Phase 01)"

DEFAULT_INPUT = "uploads/cik-sec.csv"


def _namespace(
    input_path: str, chunk_size: str, partition_count: str, workers: str
) -> argparse.Namespace:
    return argparse.Namespace(
        command="run",
        input=input_path,
        artifacts="",
        chunk_size=int(chunk_size),
        partition_count=int(partition_count),
        workers=int(workers),
        chunk=None,
        partition=None,
        limit=None,
        snapshot_id="",
    )


def _ask_configuration() -> tuple[str, str, str, str] | None:
    """Prompt for run configuration, or return None when cancelled."""
    input_path = prompt_text("Input CIK manifest", DEFAULT_INPUT)
    if not input_path:
        return None
    chunk_size = prompt_text("CIKs per chunk", "1000")
    partition_count = prompt_text("Partition count", "1")
    workers = prompt_text("Worker threads (0 = machine-derived)", "0")
    return input_path, chunk_size, partition_count, workers


def build_operator_menu() -> tuple[MenuAction, ...]:
    """Build the four operator actions bound to the shared commands."""
    return (
        MenuAction("1", "Plan generation", _action_plan),
        MenuAction("2", "Status and resume inspect", _action_status),
        MenuAction("3", "Run chunks", _action_run),
        MenuAction("4", "Merge chunks into snapshot", _action_merge),
        MenuAction("5", "Augment published snapshot", _action_augment),
    )


def _config() -> argparse.Namespace | None:
    values = _ask_configuration()
    if values is None:
        return None
    return _namespace(*values)


def _action_plan() -> None:
    args = _config()
    if args is None:
        return
    args.command = "plan"
    cmd_plan(args)


def _action_status() -> None:
    args = _config()
    if args is None:
        return
    args.command = "status"
    cmd_status(args)


def _action_run() -> None:
    args = _config()
    if args is None:
        return
    args.command = "run"
    chunk = prompt_text("Chunk id (blank = all outstanding)", "")
    partition = prompt_text("Partition id (blank = all)", "")
    args.chunk = int(chunk) if chunk else None
    args.partition = int(partition) if partition else None
    cmd_run(args)


def _action_merge() -> None:
    args = _config()
    if args is None:
        return
    args.command = "merge"
    cmd_merge(args)


def _action_augment() -> None:
    args = _config()
    if args is None:
        return
    base = prompt_text("Base snapshot id", "")
    if not base:
        return
    new = prompt_text("New snapshot id", "")
    if not new:
        return
    args.command = "augment"
    args.base_snapshot_id = base
    args.new_snapshot_id = new
    cmd_augment(args)


def main(argv: list[str] | None = None) -> int:
    """Operator entrypoint: interactive by default, CLI when given a command."""
    return operator_entrypoint(MENU_TITLE, build_operator_menu(), cli_main, argv)


if __name__ == "__main__":
    sys.exit(main())
