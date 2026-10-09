"""Interactive terminal operator for the filing-catalog pipeline.
A thin presentation layer over the same command functions the CLI uses, adding only
discovery, so the catalog and plan are picked from what is published rather than
typed. The menu never asks for an artifacts root: that has one authority already.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from edgar_sec.domain.filing_catalog.filters import parse_date_selection
from edgar_sec.domain.filing_catalog.schemas import (
    SCOPE_DETERMINISTIC,
    SCOPE_POLICY,
)
from edgar_sec.foundation.runtime.interactive import (
    MenuAction,
    PickItem,
    build_menu,
    menu_action,
    operator_entrypoint,
    prompt_paginated_choice,
    prompt_text,
)
from edgar_sec.pipelines.filing_catalog.discovery import (
    auto_policy,
    current_catalog_id,
    discover_catalogs,
    discover_plans,
    discover_policies,
)
from edgar_sec.pipelines.filing_catalog.paths import (
    FilingCatalogPaths,
    resolve_filing_catalog_paths,
    safe_identifier,
)

from .commands.expand import cmd_expand
from .commands.materialize import cmd_materialize
from .commands.plan import cmd_plan
from .commands.status import cmd_status
from .cli import main as cli_main

__all__ = ["build_operator_menu", "main"]

MENU_TITLE = "Filing Catalog (Phase 02)"


def _namespace(
    command: str,
    catalog: str = "",
    forms: str = "",
    dates: str = "",
    policy: str = "",
    scope: str = SCOPE_DETERMINISTIC,
    parent_plan: str = "",
    target_units: int = 0,
) -> argparse.Namespace:
    """Build a namespace with every field the dispatched command reads.
    Every ``cmd_*`` dereferences each field; omitting one raises inside the wizard.
    ``artifacts`` defaults to empty -- the configured project root, not an override.
    """
    return argparse.Namespace(
        command=command,
        catalog=catalog,
        forms=[f for f in forms.replace(",", " ").split() if f],
        scope=scope,
        policy=policy,
        auto_policy=False,
        suffixes=[],
        dates=dates,
        limit=None,
        source="",
        source_snapshot="",
        source_artifacts="",
        artifacts="",
        parent_plan=parent_plan,
        target_units=target_units,
    )


def _ask_catalog() -> str:
    """Pick the catalog to plan from, preferring the published pointer."""
    paths = resolve_filing_catalog_paths()
    catalogs = discover_catalogs(paths)
    if not catalogs:
        return prompt_text("Catalog id or 'current'", "current")
    current = _current_catalog_index(catalogs, paths)
    items = []
    default_item = None
    for index, catalog in enumerate(catalogs, start=1):
        is_cur = index == current
        cid = str(catalog["catalog_id"])
        marker = " [current]" if is_cur else ""
        rows = int(catalog.get("target_row_count") or 0)
        parts = int(catalog.get("part_count") or 0)
        label = f"{cid}{marker}  {rows:,} target rows, {parts} parts"
        item = PickItem(key=cid, label=label, value=catalog)
        items.append(item)
        if is_cur:
            default_item = item
    if default_item is None and items:
        default_item = items[0]
    chosen = prompt_paginated_choice(
        items,
        prompt_label="Select catalog",
        default=default_item,
    )
    if chosen is None:
        print("invalid selection; using 'current'")
        return "current"
    return str(chosen.value["catalog_id"])


def _current_catalog_index(
    catalogs: list[dict[str, Any]], paths: FilingCatalogPaths
) -> int | None:
    """1-based position of the published catalog, or ``None``."""
    current_id = current_catalog_id(paths)
    if current_id is None:
        return None
    for index, catalog in enumerate(catalogs, start=1):
        if catalog["catalog_id"] == current_id:
            return index
    return None


def _ask_parent_plan() -> tuple[str, int] | None:
    """Pick the policy plan to expand, as a resolved directory and its size."""
    paths = resolve_filing_catalog_paths()
    parents = [
        plan for plan in discover_plans(paths) if plan.get("scope") == SCOPE_POLICY
    ]
    if not parents:
        print(
            "no policy-driven plan is published to expand; publish one with "
            "'plan --scope policy' on the CLI first"
        )
        return None
    items = []
    for plan in parents:
        parent = str(plan.get("parent_plan_id") or "")
        suffix = f"  (expanded from {parent})" if parent else ""
        pid = str(plan["plan_id"])
        locators = int(plan.get("unique_locators_count") or 0)
        units = int(plan.get("target_units") or 0)
        label = f"{pid}  {locators:,} locators, {units:,} target units{suffix}"
        items.append(PickItem(key=pid, label=label, value=plan))
    chosen = prompt_paginated_choice(
        items,
        prompt_label="Select parent plan to expand",
        default=items[0],
    )
    if chosen is None:
        print("invalid selection")
        return None
    chosen_plan = chosen.value
    plan_id = str(chosen_plan["plan_id"])
    return str(paths.plan_dir(plan_id)), int(
        chosen_plan.get("unique_locators_count") or 0
    )


def _action_materialize() -> None:
    from edgar_sec.infra.storage.dag.menu import prompt_dag_target
    from .paths import resolve_metadata_paths

    meta_paths = resolve_metadata_paths()
    chosen_id = prompt_dag_target(
        meta_paths.snapshots_root,
        prompt_label="Phase 01 metadata source snapshot",
    )
    if chosen_id is None:
        return
    args = _namespace("materialize")
    args.source_snapshot = chosen_id
    cmd_materialize(args)


def _ask_dates() -> str:
    """Prompt for a report_date selection, re-asking until it parses.
    Calls the CLI's own parser, or the menu would accept what the CLI rejects. Blank
    stays valid: "no date predicate", not "no answer".
    """
    while True:
        answer = prompt_text(
            "Report dates, e.g. '@Q1[1999..2001],2005Q3..2008Q1' (blank for all)",
            "",
        ).strip()
        try:
            parse_date_selection(answer)
        except ValueError as error:
            print(f"invalid date selection: {error}")
            continue
        return answer


def _action_plan() -> None:
    catalog = _ask_catalog()
    forms = prompt_text("Forms (space separated, blank for all)", "")
    dates = _ask_dates()
    cmd_plan(_namespace("plan", catalog=catalog, forms=forms, dates=dates))


def _draft_path(paths: FilingCatalogPaths, name: str) -> Path:
    """Return the path of a named policy draft, or why the name is unusable.
    The name becomes a filename, reduced through ``safe_identifier``; two names reducing
    alike are refused rather than overwriting each other.
    """
    candidate = f"{name.strip().lower().replace(' ', '-')}.json"
    try:
        return paths.policies_root / safe_identifier(candidate)
    except ValueError:
        raise ValueError(
            f"draft name {name!r} must reduce to letters, digits, dashes, or "
            "underscores"
        ) from None


def _write_policy_draft(paths: FilingCatalogPaths, catalog: str) -> Path:
    """Write an all-forms draft for ``catalog`` and return its path.
    Derived from the catalog's own forms so an operator edits rather than authors.
    Dates and era bands stay unset: both resolve at plan time.
    """
    policy = auto_policy(catalog, paths)
    destination = _draft_path(paths, policy.corpus_id)
    policy.write(destination)
    print(f"wrote policy draft {destination}")
    print(f"  forms        {len(policy.forms)}")
    print(f"  units        {policy.base_content_units}")
    print(f"  dates        {policy.date_selection_text or '(all)'}")
    print("  era bands    derived at plan time")
    print("edit the draft, then choose it to plan")
    return destination


def _action_plan_policy() -> None:
    """Create or run a selection policy for one catalog.

    Blank always means "write a new one", never "run the first found".
    """
    catalog = _ask_catalog()
    paths = resolve_filing_catalog_paths()
    drafts = discover_policies(paths)
    if drafts:
        print("existing policy drafts:")
        for index, draft in enumerate(drafts, start=1):
            dates = draft.get("date_selection_text") or "(all)"
            bands = (
                f"{draft.get('era_band_count')} declared"
                if not draft.get("derives_era_bands")
                else "derived"
            )
            print(
                f"  {index}) {draft['name']} -- {len(draft['forms'])} forms, "
                f"{draft['base_content_units']} units, dates {dates}, bands {bands}"
            )
    else:
        print("no policy drafts found")

    while True:
        choice = prompt_text(
            "Number of a draft to plan, blank to write a new one", ""
        ).strip()
        if not choice:
            _write_policy_draft(paths, catalog)
            return
        if not choice.isdigit() or not 1 <= int(choice) <= len(drafts):
            print(f"enter a number between 1 and {len(drafts)}, or blank")
            continue
        selected = drafts[int(choice) - 1]["path"]
        cmd_plan(
            _namespace(
                "plan",
                catalog=catalog,
                policy=selected,
                scope=SCOPE_POLICY,
            )
        )
        return


def _action_expand() -> None:
    selection = _ask_parent_plan()
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
        # A contraction is not an expansion; refusing it here costs no feature build.
        print(
            f"target units {target_units:,} is smaller than the parent's "
            f"{parent_units:,}; that is a contraction, not an expansion"
        )
        return
    cmd_expand(_namespace("expand", parent_plan=parent_plan, target_units=target_units))


def _action_status() -> None:
    cmd_status(_namespace("status"))


def open_catalog_dag_console() -> None:
    """Launch interactive DAG lifecycle console for filing catalog snapshots."""
    from edgar_sec.infra.storage.dag.menu import DAGMenuConfig, run_dag_menu
    from .specs import CATALOG_RELATION_SPECS

    paths = resolve_filing_catalog_paths()
    config = DAGMenuConfig(
        snapshots_root=lambda: paths.snapshots_root,
        title="Filing Catalog Snapshot DAG Console",
        specs=CATALOG_RELATION_SPECS,
        publish_action=_action_materialize,
        publish_label="Materialize a catalog snapshot to DAG",
    )
    run_dag_menu(config)


def build_operator_menu() -> tuple[MenuAction, ...]:
    """Build the operator actions bound to the shared command functions."""
    return build_menu(
        menu_action("Report published catalogs and plans", _action_status),
        menu_action(
            "Snapshot DAG console (materialize/publish, switch current, inspect, branches, tags)",
            open_catalog_dag_console,
        ),
        menu_action("Publish a deterministic target plan", _action_plan),
        menu_action("Publish a selection policy plan", _action_plan_policy),
        menu_action("Expand a policy plan to more locators", _action_expand),
    )


def main(argv: list[str] | None = None) -> int:
    """Operator entrypoint: interactive by default, CLI when given a command."""
    return operator_entrypoint(MENU_TITLE, build_operator_menu(), cli_main, argv)


if __name__ == "__main__":
    sys.exit(main())
