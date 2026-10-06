"""Discovery-driven operator for local inventory fixtures and parser reviews."""

from __future__ import annotations

import argparse
import sys

from edgar_sec.foundation.runtime.interactive import (
    MenuAction,
    operator_entrypoint,
    prompt_text,
)
from edgar_sec.foundation.runtime.paths import resolve_paths
from edgar_sec.pipelines.document_inventory.cli import (
    cmd_fixture_create,
    cmd_fixture_fill,
    cmd_fixture_list,
    cmd_review_artifacts,
)
from edgar_sec.pipelines.document_inventory.discovery import (
    discover_fixtures,
    discover_plans,
    resolve_fixture_choice,
    resolve_plan_choice,
)
from edgar_sec.pipelines.document_inventory.cli import main as cli_main

MENU_TITLE = "Document Inventory"


def _select(lines: list[str]) -> str:
    print("\n" + "\n".join(lines))
    return prompt_text("Choice", "1").strip()


def _confirm_capture(fixture_id: str, plan_id: str) -> bool:
    print(
        f"This operation requests SEC index pages for {fixture_id} using plan {plan_id}."
    )
    return (
        prompt_text("Proceed with live SEC requests? [y/N]", "").strip().lower() == "y"
    )


def _root() -> str:
    return str(resolve_paths().artifacts_root)


def _action_create() -> None:
    plans = discover_plans(_root())
    if not plans:
        print(
            "No published catalog plans were discovered; publish a plan before creating a fixture."
        )
        return
    plan = resolve_plan_choice(plans, select=_select)
    if plan is None:
        print("Plan selection cancelled.")
        return
    fixture_id = prompt_text("Fixture id", "fixture").strip()
    if not fixture_id:
        print("Fixture id is required.")
        return
    if not _confirm_capture(fixture_id, str(plan["plan_id"])):
        print("Capture cancelled.")
        return
    cmd_fixture_create(
        argparse.Namespace(
            fixture=fixture_id,
            catalog_plan=plan["plan_id"],
            limit=None,
            artifacts="",
            json=False,
        )
    )


def _action_fill() -> None:
    fixtures = discover_fixtures(_root())
    if not fixtures:
        print("No fixtures were discovered; create a fixture first.")
        return
    fixture = resolve_fixture_choice(fixtures, select=_select)
    if fixture is None:
        print("Fixture selection cancelled.")
        return
    plans = discover_plans(_root())
    if not plans:
        print(
            "No published catalog plans were discovered; publish a plan before filling a fixture."
        )
        return
    plan = resolve_plan_choice(plans, select=_select)
    if plan is None:
        print("Plan selection cancelled.")
        return
    fixture_id = str(fixture["fixture_id"])
    plan_id = str(plan["plan_id"])
    if not _confirm_capture(fixture_id, plan_id):
        print("Capture cancelled.")
        return
    cmd_fixture_fill(
        argparse.Namespace(
            fixture=fixture_id,
            catalog_plan=plan_id,
            limit=None,
            artifacts="",
            json=False,
        )
    )


def _action_list() -> None:
    cmd_fixture_list(argparse.Namespace(artifacts="", json=False))


def _action_review() -> None:
    fixtures = discover_fixtures(_root())
    if not fixtures:
        print("No fixtures were discovered; capture a fixture first.")
        return
    fixture = resolve_fixture_choice(fixtures, select=_select)
    if fixture is None:
        print("Fixture selection cancelled.")
        return
    output = prompt_text("New review output directory", "review").strip()
    if not output:
        print("Review output directory is required.")
        return
    cmd_review_artifacts(
        argparse.Namespace(
            fixture=fixture["fixture_id"],
            output=output,
            accession=None,
            limit=None,
            workers=None,
            artifacts="",
            json=False,
        )
    )


def build_operator_menu() -> tuple[MenuAction, ...]:
    return (
        MenuAction("1", "Create fixture from a published catalog plan", _action_create),
        MenuAction("2", "Fill a discovered fixture from a catalog plan", _action_fill),
        MenuAction("3", "List discovered fixtures", _action_list),
        MenuAction("4", "Build parser review artifacts", _action_review),
    )


def main(argv: list[str] | None = None) -> int:
    return operator_entrypoint(MENU_TITLE, build_operator_menu(), cli_main, argv)


if __name__ == "__main__":
    sys.exit(main())
