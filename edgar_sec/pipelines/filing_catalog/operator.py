"""Interactive terminal operator for the filing-catalog pipeline.

The wizard is a thin presentation layer: every action delegates to the same
command functions the CLI uses, so the two surfaces cannot drift. What it adds is
discovery: the catalog and the plan an action will act on are picked from what is
published rather than typed from memory.

Expansion is the action that most needed it. ``expand`` takes a parent plan
*directory*, which no operator had ever been shown, and ``--parent-plan`` was the
only Phase 2 subcommand with no menu entry at all. It is offered here from the
same plan listing ``status`` reports, filtered to the parents expansion can
actually use.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from edgar_sec.foundation.runtime.interactive import (
    MenuAction,
    operator_entrypoint,
    prompt_text,
)

from .cli import cmd_expand, cmd_materialize, cmd_plan, cmd_status
from .cli import main as cli_main
from .discovery import current_catalog_id, discover_catalogs, discover_plans
from .paths import resolve_filing_catalog_paths
from .planner import SCOPE_DETERMINISTIC, SCOPE_POLICY

__all__ = ["build_operator_menu", "main"]

MENU_TITLE = "Filing Catalog (Phase 02)"


def _namespace(
    command: str,
    catalog: str = "",
    forms: str = "",
    artifacts: str = "",
    parent_plan: str = "",
    target_units: int = 0,
) -> argparse.Namespace:
    """Build a namespace with every field the dispatched command reads.

    The menu plans deterministically, so ``scope`` is pinned here rather than
    read from the parser: ``cmd_plan`` dereferences it, and a namespace that
    omitted it raised ``AttributeError`` inside the wizard instead of reaching the
    plan. The policy fields are present for the same reason, even though no
    menu action sets a policy scope today. The expansion fields are here for the
    same reason: ``cmd_expand`` reads both, and a menu-driven namespace that
    omitted them would fail the moment expansion was selected.
    """
    return argparse.Namespace(
        command=command,
        catalog=catalog,
        forms=[f for f in forms.replace(",", " ").split() if f],
        scope=SCOPE_DETERMINISTIC,
        policy="",
        auto_policy=False,
        amendment="both",
        suffixes=[],
        limit=None,
        source="",
        source_manifest="",
        artifacts=artifacts,
        batch_size=None,
        parent_plan=parent_plan,
        target_units=target_units,
    )


def _ask_artifacts() -> str:
    return prompt_text("Artifacts root (blank for default)", "")


def _ask_catalog(artifacts: str) -> str:
    """Pick the catalog to plan from, preferring the published pointer.

    ``--catalog`` accepts the ``current`` alias, so a blank answer already worked.
    What was missing was the list: an operator with several materialized catalogs
    had no way to see their ids from the menu, so the alias was the only reachable
    answer even when it was not the one they wanted.
    """
    paths = resolve_filing_catalog_paths(artifacts or None)
    catalogs = discover_catalogs(paths)
    if not catalogs:
        return prompt_text("Catalog id or 'current'", "current")
    current = _current_catalog_index(catalogs)
    print("\nPublished catalogs:")
    for index, catalog in enumerate(catalogs, start=1):
        marker = " [current]" if index == current else ""
        print(
            f"  {index}. {catalog['catalog_id']}{marker}  "
            f"{int(catalog.get('target_row_count') or 0):,} target rows, "
            f"{int(catalog.get('part_count') or 0)} parts"
        )
    default = "1" if current is None else str(current)
    answer = prompt_text("Catalog number", default).strip() or default
    try:
        return str(catalogs[int(answer) - 1]["catalog_id"])
    except (ValueError, IndexError):
        print("invalid selection; using 'current'")
        return "current"


def _current_catalog_index(catalogs: list[dict[str, Any]]) -> int | None:
    """1-based position of the published catalog, or ``None`` when none is set."""
    current_id = current_catalog_id(resolve_filing_catalog_paths())
    if current_id is None:
        return None
    for index, catalog in enumerate(catalogs, start=1):
        if catalog["catalog_id"] == current_id:
            return index
    return None


def _ask_parent_plan(artifacts: str) -> tuple[str, int] | None:
    """Pick the policy plan to expand, as a resolved directory and its size.

    Only policy-scope plans are offered. Expansion refuses a deterministic parent
    outright, so listing one would be offering a choice that cannot succeed.
    """
    paths = resolve_filing_catalog_paths(artifacts or None)
    parents = [
        plan for plan in discover_plans(paths) if plan.get("scope") == SCOPE_POLICY
    ]
    if not parents:
        print(
            "no policy-driven plan is published to expand; publish one with "
            "'plan --scope policy' on the CLI first"
        )
        return None
    print("\nPolicy plans available to expand:")
    for index, plan in enumerate(parents, start=1):
        parent = str(plan.get("parent_plan_id") or "")
        suffix = f"  (expanded from {parent})" if parent else ""
        print(
            f"  {index}. {plan['plan_id']}  "
            f"{int(plan.get('unique_locators_count') or 0):,} locators, "
            f"{int(plan.get('target_units') or 0):,} target units{suffix}"
        )
    answer = prompt_text("Parent plan number", "1").strip() or "1"
    try:
        chosen = parents[int(answer) - 1]
    except (ValueError, IndexError):
        print("invalid selection")
        return None
    plan_id = str(chosen["plan_id"])
    return str(paths.plan_dir(plan_id)), int(chosen.get("unique_locators_count") or 0)


def _action_materialize() -> None:
    artifacts = _ask_artifacts()
    source = prompt_text("Phase 1 metadata.parquet path (blank for current)", "")
    args = _namespace("materialize", artifacts=artifacts)
    args.source = source
    cmd_materialize(args)


def _action_plan() -> None:
    artifacts = _ask_artifacts()
    catalog = _ask_catalog(artifacts)
    forms = prompt_text("Forms (space separated, blank for all)", "")
    args = _namespace("plan", catalog=catalog, forms=forms, artifacts=artifacts)
    cmd_plan(args)


def _action_expand() -> None:
    artifacts = _ask_artifacts()
    selection = _ask_parent_plan(artifacts)
    if selection is None:
        return
    parent_plan, parent_units = selection
    target = prompt_text(
        f"Target units for the child plan (at least {parent_units:,})",
        str(max(parent_units, 1)),
    ).strip()
    try:
        target_units = int(target)
    except ValueError:
        print("target units must be a whole number")
        return
    if target_units < parent_units:
        # A contraction is not an expansion. The command refuses it as well, and
        # saying so here costs no feature build.
        print(
            f"target units {target_units:,} is smaller than the parent's "
            f"{parent_units:,}; that is a contraction, not an expansion"
        )
        return
    cmd_expand(
        _namespace(
            "expand",
            artifacts=artifacts,
            parent_plan=parent_plan,
            target_units=target_units,
        )
    )


def _action_status() -> None:
    artifacts = _ask_artifacts()
    cmd_status(_namespace("status", artifacts=artifacts))


def build_operator_menu() -> tuple[MenuAction, ...]:
    """Build the operator actions bound to the shared command functions."""
    return (
        MenuAction("1", "Report published catalogs and plans", _action_status),
        MenuAction("2", "Materialize a catalog snapshot", _action_materialize),
        MenuAction("3", "Publish a deterministic target plan", _action_plan),
        MenuAction("4", "Expand a policy plan to more locators", _action_expand),
    )


def main(argv: list[str] | None = None) -> int:
    """Operator entrypoint: interactive by default, CLI when given a command."""
    return operator_entrypoint(MENU_TITLE, build_operator_menu(), cli_main, argv)


if __name__ == "__main__":
    sys.exit(main())
