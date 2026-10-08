"""Interactive console and menu factory for distributed worker management."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from edgar_sec.foundation.runtime.interactive import (
    MenuAction,
    build_menu,
    menu_action,
    operator_entrypoint,
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
    plan_id_provider: Callable[[], str | None]
    distribution_root: Path | Callable[[], Path] | None = None
    title: str = "Worker Distribution Console"

    def resolve_root(self) -> Path:
        """Resolve base filesystem directory for worker bundles."""
        if callable(self.distribution_root):
            return self.distribution_root().resolve()
        if self.distribution_root is not None:
            return Path(self.distribution_root).resolve()
        return distribution_root().resolve()


def render_distrib_dashboard(config: DistribMenuConfig) -> str:
    """Render bounded header summary of discovered bundles and active plan."""
    root = config.resolve_root()
    plan_id = config.plan_id_provider()
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


def _action_export(config: DistribMenuConfig) -> None:
    plan_id = config.plan_id_provider()
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


def _action_run_worker(config: DistribMenuConfig) -> None:
    root = config.resolve_root()
    plan_id = config.plan_id_provider()
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


def _action_import(config: DistribMenuConfig) -> None:
    root = config.resolve_root()
    plan_id = config.plan_id_provider()
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


def _action_commands(config: DistribMenuConfig) -> None:
    plan_id = config.plan_id_provider()
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


def create_distrib_menu(config: DistribMenuConfig) -> tuple[MenuAction, ...]:
    """Construct interactive MenuAction items for distribution console."""
    root = config.resolve_root()
    actions = [
        menu_action(
            "List discovered worker bundles",
            lambda: cmd_list(config.adapter, destination=root),
        ),
        menu_action(
            "Export worker bundles for active plan", lambda: _action_export(config)
        ),
        menu_action(
            "Execute worker on a pending bundle", lambda: _action_run_worker(config)
        ),
        menu_action(
            "Adopt returned worker bundle (import)", lambda: _action_import(config)
        ),
        menu_action(
            "Render copy-pasteable execution commands", lambda: _action_commands(config)
        ),
    ]
    return build_menu(*actions)


def run_distrib_menu(config: DistribMenuConfig, argv: list[str] | None = None) -> int:
    """Launch interactive distribution console."""
    return operator_entrypoint(
        config.title,
        create_distrib_menu(config),
        lambda _argv: 0,
        argv,
        before_menu=lambda: render_distrib_dashboard(config),
    )
