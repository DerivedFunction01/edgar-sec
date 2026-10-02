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

The menu never asks for an artifacts root. That question already has one
authority -- the registered ``artifacts.root`` setting, resolved by
``resolve_paths()`` -- and asking it here would both duplicate that authority and
be asked before the catalog listing that the root determines. A non-default root
is reached with ``--artifacts`` on the subcommands instead, which is where every
other Phase 2 override lives.
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
    operator_entrypoint,
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

from .cli import cmd_expand, cmd_materialize, cmd_plan, cmd_status
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

    ``scope`` and ``policy`` default to the deterministic plan rather than being
    absent: ``cmd_plan`` dereferences both, and a namespace that omitted them
    raised ``AttributeError`` inside the wizard instead of reaching the plan. The
    defaults describe what most actions do, not what every action must do -- the
    policy-plan action overrides both. The expansion fields are here for the same
    reason: ``cmd_expand`` reads both, and a menu-driven namespace that omitted
    them would fail the moment expansion was selected.

    ``artifacts`` is pinned to the empty string for the same class of reason:
    every ``cmd_*`` reads it through the project default, and a namespace that
    omitted it would raise before the command ran. Empty is not an override --
    it resolves to the configured project root, which is the only root the menu
    acts on.
    """
    return argparse.Namespace(
        command=command,
        catalog=catalog,
        forms=[f for f in forms.replace(",", " ").split() if f],
        scope=scope,
        policy=policy,
        auto_policy=False,
        amendment="both",
        suffixes=[],
        dates=dates,
        limit=None,
        source="",
        source_manifest="",
        artifacts="",
        parent_plan=parent_plan,
        target_units=target_units,
    )


def _ask_catalog() -> str:
    """Pick the catalog to plan from, preferring the published pointer.

    ``--catalog`` accepts the ``current`` alias, so a blank answer already worked.
    What was missing was the list: an operator with several materialized catalogs
    had no way to see their ids from the menu, so the alias was the only reachable
    answer even when it was not the one they wanted.
    """
    paths = resolve_filing_catalog_paths()
    catalogs = discover_catalogs(paths)
    if not catalogs:
        return prompt_text("Catalog id or 'current'", "current")
    current = _current_catalog_index(catalogs, paths)
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


def _current_catalog_index(
    catalogs: list[dict[str, Any]], paths: FilingCatalogPaths
) -> int | None:
    """1-based position of the published catalog, or ``None`` when none is set.

    ``paths`` is the layout the listing was discovered against, passed in rather
    than re-resolved: a second resolution could read a different root and mark
    the wrong entry as current.
    """
    current_id = current_catalog_id(paths)
    if current_id is None:
        return None
    for index, catalog in enumerate(catalogs, start=1):
        if catalog["catalog_id"] == current_id:
            return index
    return None


def _ask_parent_plan() -> tuple[str, int] | None:
    """Pick the policy plan to expand, as a resolved directory and its size.

    Only policy-scope plans are offered. Expansion refuses a deterministic parent
    outright, so listing one would be offering a choice that cannot succeed.
    """
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
    source = prompt_text("Phase 1 metadata.parquet path (blank for current)", "")
    args = _namespace("materialize")
    args.source = source
    cmd_materialize(args)


def _ask_dates() -> str:
    """Prompt for a report_date selection, re-asking until it parses.

    The answer is handed to ``planner.plan`` unchanged, and this calls the same
    parser rather than a second copy of the grammar: a wizard with its own
    accepted spellings would accept things the CLI rejects and reject things it
    accepts, which is exactly the drift a menu is supposed to prevent. Blank
    stays a valid answer -- it is "no date predicate", not "no answer".
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
    """Return the path of a named policy draft, or report why the name is unusable.

    The name becomes a filename, so it is reduced to a safe identifier rather
    than sanitized by hand: two names that reduce alike are refused instead of
    overwriting each other's draft.
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

    The draft is derived from the catalog's own form list so an operator can
    inspect and edit it rather than author one from a blank file. It declares an
    empty date selection and no era bands, which is the honest starting point:
    both are resolved at plan time from whatever the operator goes on to put
    there.
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

    Two outcomes on one screen, because they are the two things an operator wants
    to do: write a draft to edit, or run a draft that already exists. A blank
    answer always means "write a new one" and never "run the first one found" --
    auto-selecting would publish a plan nobody chose.
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
        # A contraction is not an expansion. The command refuses it as well, and
        # saying so here costs no feature build.
        print(
            f"target units {target_units:,} is smaller than the parent's "
            f"{parent_units:,}; that is a contraction, not an expansion"
        )
        return
    cmd_expand(_namespace("expand", parent_plan=parent_plan, target_units=target_units))


def _action_status() -> None:
    cmd_status(_namespace("status"))


def build_operator_menu() -> tuple[MenuAction, ...]:
    """Build the operator actions bound to the shared command functions."""
    return (
        MenuAction("1", "Report published catalogs and plans", _action_status),
        MenuAction("2", "Materialize a catalog snapshot", _action_materialize),
        MenuAction("3", "Publish a deterministic target plan", _action_plan),
        MenuAction("4", "Publish a selection policy plan", _action_plan_policy),
        MenuAction("5", "Expand a policy plan to more locators", _action_expand),
    )


def main(argv: list[str] | None = None) -> int:
    """Operator entrypoint: interactive by default, CLI when given a command."""
    return operator_entrypoint(MENU_TITLE, build_operator_menu(), cli_main, argv)


if __name__ == "__main__":
    sys.exit(main())
