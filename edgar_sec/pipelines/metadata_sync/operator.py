"""Interactive terminal operator for the metadata sync pipeline.

The wizard is a thin presentation layer: every action builds the same typed
options object the CLI builds and calls the same command functions, so the two
surfaces cannot drift. There is one options model, in ``options.py``, and this
module only collects answers.
"""

from __future__ import annotations

import sys
from pathlib import Path

from edgar_sec.foundation.runtime.interactive import (
    MenuAction,
    prompt_text,
    run_interactive_menu,
)
from edgar_sec.foundation.runtime.settings import resolve_runtime_settings

from .cli import (
    cmd_augment,
    cmd_compare,
    cmd_export,
    cmd_merge,
    cmd_plan,
    cmd_refresh,
    cmd_run,
    cmd_status,
    cmd_worker,
)
from .cli import main as cli_main
from .options import (
    PlanOptions,
    RunOptions,
    plan_options,
    read_bundle_plan_id,
    run_options,
)

__all__ = ["build_operator_menu", "main"]

MENU_TITLE = "Metadata Sync (Phase 01)"

DEFAULT_INPUT = "uploads/cik-sec.csv"


def _ask_int(label: str, default: int | None = None) -> int | None:
    """Prompt for a whole number, deferring to the registry on a blank answer."""
    answer = prompt_text(label, "" if default is None else str(default)).strip()
    if not answer:
        return None
    try:
        return int(answer)
    except ValueError:
        print(f"'{answer}' is not a whole number; using the configured default")
        return None


def _ask_plan_options(*, with_limit: bool = False) -> PlanOptions | None:
    """Collect the cohort reference and chunk layout a plan needs."""
    source = prompt_text(
        "CIK manifest CSV (blank = published roster id)", DEFAULT_INPUT
    )
    if not source:
        return None
    settings = resolve_runtime_settings()
    chunk_size = _ask_int(
        "CIKs per chunk (blank = configured default)", settings.default_chunk_size
    )
    limit = _ask_int("Limit CIKs (blank = all)") if with_limit else None
    return plan_options(input_path=source, chunk_size=chunk_size, limit=limit)


def _ask_run_options(*, with_bundle: bool = False) -> RunOptions | None:
    """Collect the plan reference a status/run/merge invocation needs.

    A copied bundle names its own plan in its manifest, so the id is read from
    the bundle rather than asked for: a worker should not have to be told what
    it is already holding.
    """
    bundle = ""
    if with_bundle:
        bundle = prompt_text("Plan bundle directory (blank = local plan)", "").strip()
    plan_id = prompt_text("Plan id (blank = read from bundle)", "").strip()
    if not plan_id and bundle:
        plan_id = read_bundle_plan_id(bundle)
    if not plan_id and not bundle:
        return None
    return run_options(
        plan_id=plan_id,
        bundle_root=bundle or None,
        workers=_ask_int("Worker threads (blank = machine-derived)"),
    )


def build_operator_menu() -> tuple[MenuAction, ...]:
    """Build the operator actions bound to the shared command functions."""
    return (
        MenuAction("1", "Plan generation", _action_plan),
        MenuAction("2", "Status and resume inspect", _action_status),
        MenuAction("3", "Run chunks", _action_run),
        MenuAction("4", "Merge chunks into snapshot", _action_merge),
        MenuAction("5", "Augment published snapshot", _action_augment),
        MenuAction("6", "Export bundles for workers", _action_export),
        MenuAction("7", "Run a worker bundle", _action_worker),
        MenuAction("8", "Refresh external source", _action_refresh),
        MenuAction("9", "Compare curated input against a source", _action_compare),
    )


def _action_plan() -> None:
    options = _ask_plan_options(with_limit=True)
    if options is not None:
        cmd_plan(options)


def _action_status() -> None:
    options = _ask_run_options()
    if options is not None:
        cmd_status(options)


def _action_run() -> None:
    options = _ask_run_options()
    if options is None:
        return
    chunks = prompt_text("Chunk ids (blank = all outstanding)", "").strip()
    options.chunk_ids = (
        tuple(int(value) for value in chunks.split(",")) if chunks else ()
    )
    cmd_run(options)


def _action_merge() -> None:
    options = _ask_run_options()
    if options is not None:
        cmd_merge(options)


def _action_augment() -> None:
    options = _ask_plan_options()
    if options is None:
        return
    base = prompt_text("Base snapshot id", "").strip()
    if not base:
        return
    new = prompt_text("New snapshot id", "").strip()
    if not new:
        return
    cmd_augment(
        options,
        base_snapshot_id=base,
        new_snapshot_id=new,
        workers=_ask_int("Worker threads (blank = machine-derived)"),
    )


def _action_export() -> None:
    plan_id = prompt_text("Plan id to export", "").strip()
    if not plan_id:
        return
    destination = prompt_text("Destination directory", "").strip()
    if not destination:
        return
    worker_count = _ask_int("Worker assignments to emit", 2)
    if worker_count is None:
        return
    cmd_export(
        run_options(plan_id=plan_id),
        worker_count=worker_count,
        destination=Path(destination).resolve(),
    )


def _action_worker() -> None:
    options = _ask_run_options(with_bundle=True)
    if options is None:
        return
    worker = prompt_text("Worker id (blank = the only assignment)", "").strip()
    if worker:
        options.worker_id = worker
    cmd_worker(options)


def _action_refresh() -> None:
    artifacts = prompt_text("Artifacts root (blank = project default)", "").strip()
    cmd_refresh(Path(artifacts) if artifacts else None)


def _action_compare() -> None:
    source = prompt_text("CIK manifest CSV", DEFAULT_INPUT)
    if not source:
        return
    manifest = prompt_text("Source manifest.json path", "").strip()
    if not manifest:
        return
    artifacts = prompt_text("Artifacts root (blank = project default)", "").strip()
    cmd_compare(
        plan_options(input_path=source, artifacts_root=artifacts or None),
        source_manifest=Path(manifest).resolve(),
    )


def main(argv: list[str] | None = None) -> int:
    """Operator entrypoint: interactive by default, CLI when given a command."""
    args: list[str] = sys.argv[1:] if argv is None else list(argv)
    if not args:
        return run_interactive_menu(MENU_TITLE, build_operator_menu(), exit_key="0")
    return cli_main(args)


if __name__ == "__main__":
    sys.exit(main())
