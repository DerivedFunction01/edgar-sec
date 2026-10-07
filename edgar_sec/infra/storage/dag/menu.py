"""Pluggable interactive menu factory and dashboard for DAG operations.

Provides paginated pick-lists, bounded graph inspection, and pipeline integration.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edgar_sec.foundation.runtime.interactive import (
    MenuAction,
    operator_entrypoint,
    prompt_text,
)
from edgar_sec.foundation.runtime.settings import resolve_settings
from .cli import (
    cmd_branch,
    cmd_checkout,
    cmd_compact,
    cmd_doctor,
    cmd_gc,
    cmd_publish,
    cmd_status,
    cmd_tag,
)
from .manifest import read_manifest
from .publication import list_branches, read_pointer, read_pointer_id
from .renderer import DAGSwimlaneRenderer, build_graph_nodes
from .spec import RelationSpec
from .tags import list_tags


@dataclass(frozen=True, slots=True)
class DAGMenuConfig:
    """Configuration for an interactive DAG management console."""

    snapshots_root: Path | Callable[[], Path]
    title: str = "Snapshot DAG Console"
    specs: Sequence[RelationSpec] | Callable[[], Sequence[RelationSpec]] | None = None
    publish_action: Callable[[], Any] | None = None
    publish_label: str = "Commit completed pipeline run to DAG"
    default_graph_limit: int | None = None
    default_page_size: int | None = None

    def resolve_root(self) -> Path:
        """Resolve filesystem path for snapshot repository."""
        return (
            self.snapshots_root().resolve()
            if callable(self.snapshots_root)
            else Path(self.snapshots_root).resolve()
        )

    def resolve_specs(self) -> Sequence[RelationSpec] | None:
        """Resolve relation specs for S8 compaction."""
        if callable(self.specs):
            return self.specs()
        return self.specs


@dataclass(frozen=True, slots=True)
class PickItem:
    """One selectable item in a paginated pick-list."""

    key: str
    label: str
    value: Any


def prompt_paginated_choice(
    items: Sequence[PickItem],
    *,
    page_size: int = 15,
    prompt_label: str = "Choice",
) -> PickItem | None:
    """Interactively select an item with line-buffered pagination and filtering."""
    if not items:
        print("No items available.")
        return None

    active_filter = ""
    offset = 0

    while True:
        if active_filter:
            q = active_filter.lower()
            filtered = [
                it for it in items if q in it.key.lower() or q in it.label.lower()
            ]
        else:
            filtered = list(items)

        total = len(filtered)
        if total == 0:
            print(f"No items match filter '{active_filter}'. [c]lear to reset.")
            ans = prompt_text("[c]lear filter or [q]uit", "c").strip()
            if ans.lower() == "c":
                active_filter = ""
                offset = 0
            else:
                return None
            continue

        if offset >= total:
            offset = max(0, ((total - 1) // page_size) * page_size)

        page_items = filtered[offset : offset + page_size]
        current_page = (offset // page_size) + 1
        total_pages = max(1, (total + page_size - 1) // page_size)

        filter_banner = f" | Filter: '{active_filter}'" if active_filter else ""
        print(
            f"\nShowing {offset + 1}-{offset + len(page_items)} of {total} items "
            f"(Page {current_page}/{total_pages}{filter_banner}):"
        )
        for idx, it in enumerate(page_items, start=1):
            print(f"  [{idx}] {it.label}")

        nav_options: list[str] = [f"1-{len(page_items)}"]
        if current_page < total_pages:
            nav_options.append("[n]ext")
        if current_page > 1:
            nav_options.append("[p]rev")
        if active_filter:
            nav_options.append("[c]lear filter")
        nav_options.append("[q]uit")

        prompt_msg = f"{prompt_label} ({', '.join(nav_options)} or type text to filter)"
        choice = prompt_text(prompt_msg, "").strip()

        if not choice or choice.lower() == "q":
            return None
        if choice.lower() == "n":
            if current_page < total_pages:
                offset += page_size
            continue
        if choice.lower() == "p":
            if current_page > 1:
                offset -= page_size
            continue
        if choice.lower() == "c":
            active_filter = ""
            offset = 0
            continue
        if choice.isdigit():
            val = int(choice)
            if 1 <= val <= len(page_items):
                return page_items[val - 1]
            print(f"Selection must be between 1 and {len(page_items)}.")
            continue

        active_filter = choice
        offset = 0


def render_dag_dashboard(config: DAGMenuConfig) -> str:
    """Render bounded O(1) header summary of the active snapshot repository."""
    root = config.resolve_root()
    lines = ["=" * 72, f"   {config.title}", f"   Root: {root}"]

    if not root.exists():
        lines.append("   Status: Uninitialized repository (no snapshots yet)")
        lines.append("=" * 72)
        return "\n".join(lines)

    ptr = read_pointer(root)
    branches = list_branches(root)
    tags = list_tags(root)

    staged_dirs = (
        [
            d.name
            for d in sorted(root.iterdir())
            if d.is_dir() and d.name.startswith(".stage-")
        ]
        if root.is_dir()
        else []
    )

    if ptr is not None:
        tip_id = str(ptr["snapshot_id"])
        manifest_file = root / tip_id / "manifest.json"
        if manifest_file.is_file():
            tip = read_manifest(manifest_file)
            lines.append(
                f"   HEAD: (branch: current) -> {tip_id} ({tip.kind}) | Depth: {tip.lineage_depth}"
            )
            rel_counts = f"{len(tip.relations)} relations"
            lines.append(
                f"   Anchor: {tip.checkpoint_anchor_id} | {rel_counts} | Branches: {len(branches)} | Tags: {len(tags)}"
            )
        else:
            lines.append(f"   HEAD: {tip_id} (manifest missing!)")
    else:
        lines.append(
            f"   HEAD: No active pointer | Branches: {len(branches)} | Tags: {len(tags)}"
        )

    if staged_dirs:
        lines.append(
            f"   Staged Runs: {len(staged_dirs)} detected ({', '.join(staged_dirs[:3])})"
        )
    lines.append("=" * 72)
    return "\n".join(lines)


def run_paginated_graph(
    root: Path,
    *,
    branch_name: str | None = None,
    limit: int = 25,
) -> None:
    """Interactive paginated and filterable swimlane graph viewer."""
    graph_nodes = build_graph_nodes(root, branch_name=branch_name, all_heads=True)
    if not graph_nodes:
        print("No nodes found in graph.")
        return

    renderer = DAGSwimlaneRenderer(graph_nodes)
    offset = 0
    active_filter = ""

    while True:
        text = renderer.render(offset=offset, limit=limit, filter_text=active_filter)
        print("\n=== DAG SWIMLANE VIEW ===")
        print(text if text.strip() else "(no matching nodes)")
        print("-" * 40)
        filter_str = f" | Filter: '{active_filter}'" if active_filter else ""
        print(f"Viewing offset {offset}{filter_str}")

        ans = prompt_text(
            "[n]ext, [p]rev, [c]lear, [q]uit, or type filter text", ""
        ).strip()
        if not ans or ans.lower() == "q":
            break
        if ans.lower() == "n":
            offset += limit
            continue
        if ans.lower() == "p":
            offset = max(0, offset - limit)
            continue
        if ans.lower() == "c":
            active_filter = ""
            offset = 0
            continue
        active_filter = ans
        offset = 0


def _action_checkout(config: DAGMenuConfig) -> None:
    root = config.resolve_root()
    branches = list_branches(root)
    tags = list_tags(root)
    items: list[PickItem] = []

    for b in branches:
        b_ptr = read_pointer(root, branch_name=None if b == "current" else b)
        s_id = str(b_ptr["snapshot_id"]) if b_ptr else "none"
        prefix = "* " if b == "current" else "  "
        items.append(
            PickItem(
                key=b,
                label=f"{prefix}branch: {b:<14} -> {s_id}",
                value=s_id,
            )
        )
    for t in tags:
        items.append(
            PickItem(
                key=t["tag"],
                label=f"  tag: {t['tag']:<17} -> {t['snapshot_id']}",
                value=t["tag"],
            )
        )

    chosen = prompt_paginated_choice(items, prompt_label="Select target to checkout")
    if chosen is not None:
        cmd_checkout(root, chosen.value)


def _action_publish_staged(config: DAGMenuConfig) -> None:
    root = config.resolve_root()
    staged = [
        d for d in sorted(root.iterdir()) if d.is_dir() and d.name.startswith(".stage-")
    ]
    if not staged:
        print("No staged directories (.stage-*) found to publish.")
        return

    items = [PickItem(key=d.name, label=d.name, value=d) for d in staged]
    chosen = prompt_paginated_choice(items, prompt_label="Select staged directory")
    if chosen is not None:
        cmd_publish(root, chosen.value)


def create_dag_menu(config: DAGMenuConfig) -> tuple[MenuAction, ...]:
    """Construct MenuAction tuple for interactive DAG management."""
    root = config.resolve_root()
    actions: list[MenuAction] = []
    idx = 1

    if config.publish_action is not None:
        actions.append(
            MenuAction(
                str(idx),
                config.publish_label,
                config.publish_action,
            )
        )
        idx += 1

    actions.append(
        MenuAction(
            str(idx),
            "Publish detected staging directory (.stage-*)",
            lambda: _action_publish_staged(config),
        )
    )
    idx += 1

    actions.append(
        MenuAction(
            str(idx),
            "View ASCII swimlane graph (paginated & filterable)",
            lambda: run_paginated_graph(root, limit=config.default_graph_limit or 25),
        )
    )
    idx += 1

    actions.append(
        MenuAction(str(idx), "Quick status & metrics", lambda: cmd_status(root))
    )
    idx += 1

    actions.append(
        MenuAction(
            str(idx),
            "Checkout / switch tip (pick-list: branches, tags, snapshots)",
            lambda: _action_checkout(config),
        )
    )
    idx += 1

    actions.append(
        MenuAction(
            str(idx),
            "Branch management (list, create, delete)",
            lambda: cmd_branch(root, action="list"),
        )
    )
    idx += 1

    actions.append(
        MenuAction(
            str(idx),
            "Tag management (list, create, delete)",
            lambda: cmd_tag(root, action="list"),
        )
    )
    idx += 1

    actions.append(
        MenuAction(
            str(idx),
            "Compact lineage (S8 Checkpoint parity merge)",
            lambda: cmd_compact(root, specs_target=None),
        )
    )
    idx += 1

    actions.append(
        MenuAction(
            str(idx),
            "Run integrity doctor (verify digests, cycles, parts)",
            lambda: cmd_doctor(root, verify_digests=True),
        )
    )
    idx += 1

    actions.append(
        MenuAction(
            str(idx),
            "Garbage collection (discover & purge unreferenced)",
            lambda: cmd_gc(root, dry_run=False),
        )
    )
    return tuple(actions)


def run_dag_menu(config: DAGMenuConfig, argv: list[str] | None = None) -> int:
    """Run interactive DAG console bound to configuration."""
    resolved = resolve_settings()
    page_size = int(resolved.get("dag.page_size", 15))
    graph_limit = int(resolved.get("dag.graph_limit", 25))

    effective_config = DAGMenuConfig(
        snapshots_root=config.snapshots_root,
        title=config.title,
        specs=config.specs,
        publish_action=config.publish_action,
        publish_label=config.publish_label,
        default_graph_limit=config.default_graph_limit or graph_limit,
        default_page_size=config.default_page_size or page_size,
    )

    return operator_entrypoint(
        effective_config.title,
        create_dag_menu(effective_config),
        lambda _argv: 0,
        argv,
        before_menu=lambda: render_dag_dashboard(effective_config),
    )


__all__ = [
    "DAGMenuConfig",
    "PickItem",
    "create_dag_menu",
    "prompt_paginated_choice",
    "render_dag_dashboard",
    "run_dag_menu",
    "run_paginated_graph",
]
