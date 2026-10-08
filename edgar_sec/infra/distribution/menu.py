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
    """Configuration for an interactive distribution console."""

    adapter: DistributionAdapter
    plan_id: str | None = None
    plans_root: Path | str | None = None
    distribution_root: Path | Callable[[], Path] | None = None
    title: str = "Worker Distribution Console"

    def resolve_root(self) -> Path:
        """Resolve base filesystem directory for worker bundles."""
        if callable(self.distribution_root):
            return self.distribution_root().resolve()
        if self.distribution_root is not None:
            return Path(self.distribution_root).resolve()
        return distribution_root().resolve()


class DistribSession:
    """State for an active distribution menu session."""

    def __init__(self, plan_id: str | None = None) -> None:
        self.plan_id = plan_id

    def get_or_prompt_plan(self, config: DistribMenuConfig) -> str | None:
        if self.plan_id:
            return self.plan_id
        if config.plans_root:
            from edgar_sec.domain.plan.discovery import discover_plans

            plans = discover_plans(config.plans_root)
            if not plans:
                print("No published plans discovered.")
                return None
            items = [
                PickItem(key=p.plan_id, label=p.describe(), value=p) for p in plans
            ]
            chosen = prompt_paginated_choice(
                items, prompt_label="Select plan", default=items[0]
            )
            if chosen is not None:
                self.plan_id = chosen.value.plan_id
                return self.plan_id
        return None


def render_distrib_dashboard(
    config: DistribMenuConfig, active_plan_id: str | None = None
) -> str:
    """Render bounded header summary of discovered bundles and active plan."""
    root = config.resolve_root()
    plan_id = active_plan_id or config.plan_id
    p_name = config.adapter.pipeline_name

    lines = [
        "=" * 72,
        f"   {config.title} ({p_name})",
        f"   Distribution Root: {root}",
    ]

    if plan_id:
        try:
            plan = config.adapter.resolve_plan(plan_id, None)
            total_chunks = config.adapter.get_chunk_count(plan)
            lines.append(f"   Active Plan: {plan_id} ({total_chunks} chunks)")
        except Exception:  # noqa: BLE001
            lines.append(f"   Active Plan: {plan_id} (unreadable)")
    else:
        lines.append("   Active Plan: None selected")

    bundles = discover_bundles(root, pipeline=p_name, plan_id=plan_id)
    completed = sum(1 for b in bundles if b.state == "completed")
    pending = sum(1 for b in bundles if b.state == "pending")
    lines.append(
        f"   Discovered Bundles: {len(bundles)} ({completed} completed, {pending} pending)"
    )
    lines.append("=" * 72)
    return "\n".join(lines)


def _action_export(config: DistribMenuConfig, session: DistribSession) -> None:
    plan_id = session.get_or_prompt_plan(config)
    if not plan_id:
        print("No active plan selected. Select or publish a plan first.")
        return

    workers_str = prompt_text("Number of worker bundles", "2").strip()
    try:
        workers = max(1, int(workers_str))
    except ValueError:
        print("Invalid worker count.")
        return

    default_dest = config.adapter.default_destination(plan_id)
    dest_str = prompt_text("Destination directory", str(default_dest)).strip()
    dest = Path(dest_str) if dest_str else default_dest

    cmd_export(config.adapter, plan_id, worker_count=workers, destination=dest)


def _action_run_worker(config: DistribMenuConfig, session: DistribSession) -> None:
    root = config.resolve_root()
    plan_id = session.get_or_prompt_plan(config)
    bundles = [
        b
        for b in discover_bundles(
            root, pipeline=config.adapter.pipeline_name, plan_id=plan_id
        )
        if b.state == "pending"
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
    plan_id = session.get_or_prompt_plan(config)
    if not plan_id:
        print("No active plan selected.")
        return

    bundles = [
        b
        for b in discover_bundles(
            root, pipeline=config.adapter.pipeline_name, plan_id=plan_id
        )
        if b.state == "completed"
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

    cmd_import(config.adapter, plan_id, chosen.bundle_dir)


def _action_commands(config: DistribMenuConfig, session: DistribSession) -> None:
    plan_id = session.get_or_prompt_plan(config)
    if not plan_id:
        print("No active plan selected.")
        return

    workers_str = prompt_text("Number of workers", "2").strip()
    try:
        workers = max(1, int(workers_str))
    except ValueError:
        workers = 2

    default_dest = config.adapter.default_destination(plan_id)
    dest_str = prompt_text("Destination directory", str(default_dest)).strip()
    dest = Path(dest_str) if dest_str else default_dest

    cmd_commands(config.adapter, plan_id, worker_count=workers, destination=dest)


def _action_switch_plan(config: DistribMenuConfig, session: DistribSession) -> None:
    if not config.plans_root:
        print("No plans directory configured for this console.")
        return
    from edgar_sec.domain.plan.discovery import discover_plans

    plans = discover_plans(config.plans_root)
    if not plans:
        print("No published plans discovered.")
        return
    items = [PickItem(key=p.plan_id, label=p.describe(), value=p) for p in plans]
    chosen = prompt_paginated_choice(
        items,
        prompt_label="Select active plan",
        default=items[0],
    )
    if chosen is not None:
        session.plan_id = chosen.value.plan_id
        print(f"Active plan switched to {session.plan_id}")


def create_distrib_menu(
    config: DistribMenuConfig, session: DistribSession | None = None
) -> tuple[MenuAction, ...]:
    """Construct interactive MenuAction items for distribution console."""
    root = config.resolve_root()
    active_session = session or DistribSession(config.plan_id)
    actions = [
        menu_action(
            "List discovered worker bundles",
            lambda: cmd_list(config.adapter, destination=root),
        ),
        menu_action(
            "Export worker bundles for active plan",
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
            "Render copy-pasteable execution commands",
            lambda: _action_commands(config, active_session),
        ),
    ]
    if config.plans_root:
        actions.append(
            menu_action(
                "Switch active plan",
                lambda: _action_switch_plan(config, active_session),
                key="s",
            )
        )
    return build_menu(*actions)


def run_distrib_menu(
    config: DistribMenuConfig,
    argv: list[str] | None = None,
    session: DistribSession | None = None,
) -> int:
    """Launch interactive distribution console."""
    active_session = session or DistribSession(config.plan_id)
    return operator_entrypoint(
        config.title,
        create_distrib_menu(config, active_session),
        lambda _argv: 0,
        argv,
        before_menu=lambda: render_distrib_dashboard(config, active_session.plan_id),
    )
