"""Interactive console and menu factory for distributed worker management."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from edgar_sec.foundation.runtime.interactive import (
    MenuAction,
    PickItem,
    build_menu,
    menu_action,
    operator_entrypoint,
    prompt_paginated_choice,
    prompt_text,
)
from edgar_sec.foundation.runtime.paths import distribution_root

from .cli import cmd_commands, cmd_export, cmd_import, cmd_list, cmd_worker
from .discovery import discover_bundles, resolve_bundle_choice
from .protocol import DistributionAdapter


@dataclass(frozen=True, slots=True)
class DistribMenuConfig:
    adapter: DistributionAdapter
    work_id: str | None = None
    artifacts_root: Path | None = None
    distribution_root: Path | Callable[[], Path] | None = None
    title: str = "Worker Distribution Console"

    def resolve_root(self) -> Path:
        if callable(self.distribution_root):
            return self.distribution_root().resolve()
        if self.distribution_root is not None:
            return Path(self.distribution_root).resolve()
        return distribution_root().resolve()


class DistribSession:
    def __init__(self, work_id: str | None = None) -> None:
        self.work_id = work_id

    def get_or_prompt_work(self, config: DistribMenuConfig) -> str | None:
        if self.work_id:
            return self.work_id
        work_items = config.adapter.list_work_items(config.artifacts_root)
        if not work_items:
            print("No distributable work items discovered.")
            return None
        items = [
            PickItem(
                key=item.work_id,
                label=(
                    f"{item.label}  {item.chunk_count} chunks  {item.work_digest[:12]}"
                ),
                value=item,
            )
            for item in work_items
        ]
        chosen = prompt_paginated_choice(
            items, prompt_label="Select work item", default=items[0]
        )
        if chosen is None:
            return None
        self.work_id = chosen.value.work_id
        return self.work_id


def render_distrib_dashboard(
    config: DistribMenuConfig, active_work_id: str | None = None
) -> str:
    root = config.resolve_root()
    work_id = active_work_id or config.work_id
    pipeline = config.adapter.pipeline_name
    lines = [
        "=" * 72,
        f"   {config.title} ({pipeline})",
        f"   Distribution Root: {root}",
    ]
    if work_id:
        try:
            work = config.adapter.resolve_work(work_id, config.artifacts_root)
            summary = config.adapter.describe_work(work_id, work)
            lines.append(
                f"   Active Work: {summary.label} [{work_id}] "
                f"({summary.chunk_count} chunks)"
            )
        except (OSError, ValueError, KeyError):
            lines.append(f"   Active Work: {work_id} (unreadable)")
    else:
        lines.append("   Active Work: None selected")

    bundles = discover_bundles(root, pipeline=pipeline, work_id=work_id)
    completed = sum(bundle.state == "completed" for bundle in bundles)
    pending = sum(bundle.state == "pending" for bundle in bundles)
    corrupt = sum(bundle.state == "corrupt" for bundle in bundles)
    lines.append(
        f"   Discovered Bundles: {len(bundles)} "
        f"({completed} completed, {pending} pending, {corrupt} corrupt)"
    )
    lines.append("=" * 72)
    return "\n".join(lines)


def _action_export(config: DistribMenuConfig, session: DistribSession) -> None:
    work_id = session.get_or_prompt_work(config)
    if not work_id:
        return
    worker_text = prompt_text("Number of worker bundles", "2").strip()
    try:
        workers = max(1, int(worker_text))
    except ValueError:
        print("Invalid worker count.")
        return
    default_destination = config.adapter.default_destination(work_id)
    destination_text = prompt_text(
        "Destination directory", str(default_destination)
    ).strip()
    destination = Path(destination_text) if destination_text else default_destination
    cmd_export(
        config.adapter,
        work_id,
        worker_count=workers,
        destination=destination,
        artifacts_root=config.artifacts_root,
    )


def _action_run_worker(config: DistribMenuConfig, session: DistribSession) -> None:
    root = config.resolve_root()
    work_id = session.get_or_prompt_work(config)
    bundles = [
        bundle
        for bundle in discover_bundles(
            root, pipeline=config.adapter.pipeline_name, work_id=work_id
        )
        if bundle.state == "pending"
    ]
    if not bundles:
        print("No pending worker bundles discovered.")
        return
    chosen = resolve_bundle_choice(
        bundles,
        lambda lines: prompt_text("\n".join(lines) + "\nSelect worker bundle", "1"),
    )
    if chosen is None:
        print("Worker selection cancelled.")
        return
    cmd_worker(config.adapter, chosen.bundle_dir, worker_id=chosen.worker_id)


def _action_import(config: DistribMenuConfig, session: DistribSession) -> None:
    root = config.resolve_root()
    work_id = session.get_or_prompt_work(config)
    if not work_id:
        return
    bundles = [
        bundle
        for bundle in discover_bundles(
            root, pipeline=config.adapter.pipeline_name, work_id=work_id
        )
        if bundle.state == "completed"
    ]
    if not bundles:
        print("No completed worker bundles with valid receipts discovered.")
        return
    chosen = resolve_bundle_choice(
        bundles,
        lambda lines: prompt_text("\n".join(lines) + "\nSelect bundle to import", "1"),
    )
    if chosen is None:
        print("Import selection cancelled.")
        return
    cmd_import(
        config.adapter,
        work_id,
        chosen.bundle_dir,
        artifacts_root=config.artifacts_root,
    )


def _action_commands(config: DistribMenuConfig, session: DistribSession) -> None:
    work_id = session.get_or_prompt_work(config)
    if not work_id:
        return
    worker_text = prompt_text("Number of workers", "2").strip()
    try:
        workers = max(1, int(worker_text))
    except ValueError:
        workers = 2
    default_destination = config.adapter.default_destination(work_id)
    destination_text = prompt_text(
        "Destination directory", str(default_destination)
    ).strip()
    destination = Path(destination_text) if destination_text else default_destination
    cmd_commands(
        config.adapter,
        work_id,
        worker_count=workers,
        destination=destination,
        artifacts_root=config.artifacts_root,
    )


def _action_switch_work(config: DistribMenuConfig, session: DistribSession) -> None:
    work_items = config.adapter.list_work_items(config.artifacts_root)
    if not work_items:
        print("No distributable work items discovered.")
        return
    items = [
        PickItem(
            key=item.work_id,
            label=f"{item.label}  {item.chunk_count} chunks  {item.work_digest[:12]}",
            value=item,
        )
        for item in work_items
    ]
    chosen = prompt_paginated_choice(
        items, prompt_label="Select active work item", default=items[0]
    )
    if chosen is not None:
        session.work_id = chosen.value.work_id
        print(f"Active work switched to {session.work_id}")


def create_distrib_menu(
    config: DistribMenuConfig, session: DistribSession | None = None
) -> tuple[MenuAction, ...]:
    root = config.resolve_root()
    active_session = session or DistribSession(config.work_id)
    actions = [
        menu_action(
            "List discovered worker bundles",
            lambda: cmd_list(config.adapter, destination=root),
        ),
        menu_action(
            "Export worker bundles for active work",
            lambda: _action_export(config, active_session),
        ),
        menu_action(
            "Execute worker on a pending bundle",
            lambda: _action_run_worker(config, active_session),
        ),
        menu_action(
            "Adopt returned worker bundle (import)",
            lambda: _action_import(config, active_session),
        ),
        menu_action(
            "Render distributed execution commands",
            lambda: _action_commands(config, active_session),
        ),
        menu_action(
            "Switch active work item",
            lambda: _action_switch_work(config, active_session),
            key="s",
        ),
    ]
    return build_menu(*actions)


def run_distrib_menu(
    config: DistribMenuConfig,
    argv: list[str] | None = None,
    session: DistribSession | None = None,
) -> int:
    active_session = session or DistribSession(config.work_id)
    return operator_entrypoint(
        config.title,
        create_distrib_menu(config, active_session),
        lambda _argv: 0,
        argv,
        before_menu=lambda: render_distrib_dashboard(config, active_session.work_id),
    )
