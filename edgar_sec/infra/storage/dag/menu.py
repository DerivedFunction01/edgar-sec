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
    PickItem,
    build_menu,
    menu_action,
    operator_entrypoint,
    prompt_paginated_choice,
    prompt_text,
)
from edgar_sec.foundation.runtime.settings import resolve_settings
from edgar_sec.foundation.runtime.settings.dag import DEFAULT_DAG_GRAPH_LIMIT
from edgar_sec.foundation.runtime.settings.interactive import DEFAULT_PAGE_SIZE
from edgar_sec.infra.storage.dag.paths import DAGPaths, STAGING_PREFIX
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
from .catalog import DAGCatalog
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
            if d.is_dir() and DAGPaths.is_staging_name(d.name)
        ]
        if root.is_dir()
        else []
    )

    if ptr is not None:
        tip_id = str(ptr["snapshot_id"])
        catalog = DAGCatalog(root)
        tip = catalog.get_manifest(tip_id)
        if tip is not None:
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


def collect_dag_targets(snapshots_root: Path | str) -> list[PickItem]:
    """Collect selectable branch and tag targets for a DAG repository."""
    root = Path(snapshots_root)
    branches = list_branches(root)
    tags = list_tags(root)
    items: list[PickItem] = []

    for b in branches:
        b_ptr = read_pointer(root, branch_name=b)
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
                value=t["snapshot_id"],
            )
        )
    return items


def prompt_dag_target(
    snapshots_root: Path | str,
    *,
    prompt_label: str = "Select target",
) -> str | None:
    """Interactively select a target snapshot from a DAG repository."""
    items = collect_dag_targets(snapshots_root)
    if not items:
        print("No published snapshot targets available.")
        return None
    chosen = prompt_paginated_choice(
        items,
        prompt_label=prompt_label,
        default=items[0],
    )
    return str(chosen.value) if chosen is not None else None


def _action_checkout(config: DAGMenuConfig) -> None:
    root = config.resolve_root()
    target = prompt_dag_target(root, prompt_label="Select target to checkout")
    if target is not None:
        cmd_checkout(root, target)


def _action_branch(config: DAGMenuConfig) -> None:
    root = config.resolve_root()
    sub = prompt_text(
        "Branch Management: 1 List, 2 Create, 3 Delete (blank = 1)", "1"
    ).strip()
    if sub in ("", "1"):
        branches = list_branches(root)
        if not branches:
            print("No branches found.")
            return
        items = []
        for b in branches:
            ptr = read_pointer(root, branch_name=None if b == "current" else b)
            s_id = str(ptr["snapshot_id"]) if ptr else "none"
            prefix = "* " if b == "current" else "  "
            items.append(PickItem(key=b, label=f"{prefix}{b:<16} -> {s_id}", value=b))
        prompt_paginated_choice(items, prompt_label="Branches")
    elif sub == "2":
        name = prompt_text("Branch name", "").strip()
        if not name:
            print("Branch name cannot be blank.")
            return
        target_id = prompt_dag_target(root, prompt_label="Select source snapshot")
        if target_id is None:
            curr_ptr = read_pointer(root)
            target_id = str(curr_ptr["snapshot_id"]) if curr_ptr else None
        if not target_id:
            print("No snapshot available to branch from.")
            return
        cmd_branch(root, action="create", name=name, from_snapshot_id=target_id)
    elif sub == "3":
        branches = [b for b in list_branches(root) if b != "current"]
        if not branches:
            print("No deletable branches found (cannot delete current).")
            return
        items = [PickItem(key=b, label=f"branch: {b}", value=b) for b in branches]
        chosen = prompt_paginated_choice(items, prompt_label="Select branch to delete")
        if chosen is not None:
            cmd_branch(root, action="delete", name=chosen.value)


def _action_tag(config: DAGMenuConfig) -> None:
    root = config.resolve_root()
    sub = prompt_text(
        "Tag Management: 1 List, 2 Create, 3 Delete (blank = 1)", "1"
    ).strip()
    if sub in ("", "1"):
        tags = list_tags(root)
        if not tags:
            print("No tags found.")
            return
        items = []
        for t in tags:
            msg = f" [{t['message']}]" if t.get("message") else ""
            date = t.get("created_at", "")[:10]
            items.append(
                PickItem(
                    key=t["tag"],
                    label=f"{t['tag']:<16} -> {t['snapshot_id']} ({date}){msg}",
                    value=t["tag"],
                )
            )
        prompt_paginated_choice(items, prompt_label="Tags")
    elif sub == "2":
        name = prompt_text("Tag name", "").strip()
        if not name:
            print("Tag name cannot be blank.")
            return
        target_id = prompt_dag_target(root, prompt_label="Select target snapshot")
        if target_id is None:
            curr_ptr = read_pointer(root)
            target_id = str(curr_ptr["snapshot_id"]) if curr_ptr else None
        if not target_id:
            print("No snapshot available to tag.")
            return
        msg = prompt_text("Message (optional)", "").strip()
        cmd_tag(root, action="create", name=name, target=target_id, message=msg)
    elif sub == "3":
        tags = list_tags(root)
        if not tags:
            print("No tags found to delete.")
            return
        items = [
            PickItem(
                key=t["tag"],
                label=f"tag: {t['tag']} -> {t['snapshot_id']}",
                value=t["tag"],
            )
            for t in tags
        ]
        chosen = prompt_paginated_choice(items, prompt_label="Select tag to delete")
        if chosen is not None:
            cmd_tag(root, action="delete", name=chosen.value)


def _action_publish_staged(config: DAGMenuConfig) -> None:
    root = config.resolve_root()
    staged = [
        d
        for d in sorted(root.iterdir())
        if d.is_dir() and DAGPaths.is_staging_name(d.name)
    ]
    if not staged:
        print(f"No staged directories ({STAGING_PREFIX}*) found to publish.")
        return

    items = [PickItem(key=d.name, label=d.name, value=d) for d in staged]
    chosen = prompt_paginated_choice(items, prompt_label="Select staged directory")
    if chosen is not None:
        cmd_publish(root, chosen.value)


def create_dag_menu(config: DAGMenuConfig) -> tuple[MenuAction, ...]:
    """Construct MenuAction tuple for interactive DAG management."""
    root = config.resolve_root()
    actions: list[MenuAction] = []

    if config.publish_action is not None:
        actions.append(menu_action(config.publish_label, config.publish_action))

    actions.append(
        menu_action(
            f"Publish detected staging directory ({STAGING_PREFIX}*)",
            lambda: _action_publish_staged(config),
        )
    )
    actions.append(
        menu_action(
            "View ASCII swimlane graph (paginated & filterable)",
            lambda: run_paginated_graph(
                root, limit=config.default_graph_limit or DEFAULT_DAG_GRAPH_LIMIT
            ),
        )
    )
    actions.append(menu_action("Quick status & metrics", lambda: cmd_status(root)))
    actions.append(
        menu_action(
            "Checkout / switch tip (pick-list: branches, tags, snapshots)",
            lambda: _action_checkout(config),
        )
    )
    actions.append(
        menu_action(
            "Branch management (list, create, delete)",
            lambda: _action_branch(config),
        )
    )
    actions.append(
        menu_action(
            "Tag management (list, create, delete)",
            lambda: _action_tag(config),
        )
    )
    actions.append(
        menu_action(
            "Compact lineage (S8 Checkpoint parity merge)",
            lambda: cmd_compact(root, specs_target=None),
        )
    )
    actions.append(
        menu_action(
            "Run integrity doctor (verify digests, cycles, parts)",
            lambda: cmd_doctor(root, verify_digests=True),
        )
    )
    actions.append(
        menu_action(
            "Garbage collection (discover & purge unreferenced)",
            lambda: cmd_gc(root, dry_run=False),
        )
    )
    return build_menu(*actions)


def run_dag_menu(config: DAGMenuConfig, argv: list[str] | None = None) -> int:
    """Run interactive DAG console bound to configuration."""
    resolved = resolve_settings()
    page_size = int(resolved.get("interactive.page_size", DEFAULT_PAGE_SIZE))
    graph_limit = int(resolved.get("dag.graph_limit", DEFAULT_DAG_GRAPH_LIMIT))

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
    "collect_dag_targets",
    "create_dag_menu",
    "prompt_dag_target",
    "render_dag_dashboard",
    "run_dag_menu",
    "run_paginated_graph",
]
