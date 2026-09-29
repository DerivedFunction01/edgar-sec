"""Interactive terminal operator for the filing-catalog pipeline.

The wizard is a thin presentation layer: every action delegates to the same
command functions the CLI uses, so the two surfaces cannot drift.
"""

from __future__ import annotations

import argparse
import sys

from edgar_sec.foundation.runtime.interactive import (
    MenuAction,
    operator_entrypoint,
    prompt_text,
)

from .cli import cmd_materialize, cmd_plan, cmd_status
from .cli import main as cli_main
from .planner import SCOPE_DETERMINISTIC

__all__ = ["build_operator_menu", "main"]

MENU_TITLE = "Filing Catalog (Phase 02)"


def _namespace(
    command: str, catalog: str = "", forms: str = "", artifacts: str = ""
) -> argparse.Namespace:
    """Build a namespace with every field the dispatched command reads.

    The menu plans deterministically, so ``scope`` is pinned here rather than
    read from the parser: ``cmd_plan`` dereferences it, and a namespace that
    omitted it raised ``AttributeError`` inside the wizard instead of reaching
    the plan. The policy fields are present for the same reason, even though no
    menu action sets a policy scope today.
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
    )


def _ask_artifacts() -> str:
    return prompt_text("Artifacts root (blank for default)", "")


def _action_materialize() -> None:
    artifacts = _ask_artifacts()
    source = prompt_text("Phase 1 metadata.parquet path (blank for current)", "")
    args = _namespace("materialize", artifacts=artifacts)
    args.source = source
    cmd_materialize(args)


def _action_plan() -> None:
    artifacts = _ask_artifacts()
    catalog = prompt_text("Catalog id or 'current'", "current")
    forms = prompt_text("Forms (space separated, blank for all)", "")
    args = _namespace("plan", catalog=catalog, forms=forms, artifacts=artifacts)
    cmd_plan(args)


def _action_status() -> None:
    artifacts = _ask_artifacts()
    cmd_status(_namespace("status", artifacts=artifacts))


def build_operator_menu() -> tuple[MenuAction, ...]:
    """Build the operator actions bound to the shared command functions."""
    return (
        MenuAction("1", "Report published catalogs and plans", _action_status),
        MenuAction("2", "Materialize a catalog snapshot", _action_materialize),
        MenuAction("3", "Publish a deterministic target plan", _action_plan),
    )


def main(argv: list[str] | None = None) -> int:
    """Operator entrypoint: interactive by default, CLI when given a command."""
    return operator_entrypoint(MENU_TITLE, build_operator_menu(), cli_main, argv)


if __name__ == "__main__":
    sys.exit(main())
