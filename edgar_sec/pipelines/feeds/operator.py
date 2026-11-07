"""Interactive terminal operator for the feeds ledger pipeline.

A thin presentation layer over the same command functions the CLI uses, so
the two surfaces cannot drift.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from edgar_sec.foundation.runtime.interactive import (
    MenuAction,
    build_menu,
    menu_action,
    operator_entrypoint,
    prompt_text,
)

from .cli import main as cli_main
from .commands.backfill import cmd_backfill
from .commands.run import cmd_run
from .commands.status import cmd_status
from .ledger import ledger_tip
from .options import feeds_options, parse_month
from .paths import resolve_feeds_paths

__all__ = [
    "WizardState",
    "build_operator_menu",
    "confirm_network",
    "main",
    "render_session_header",
]

MENU_TITLE = "Structured Disclosure Feeds"

NETWORK_PROMPT = "This contacts SEC over the network. Continue? (y/N) "


@dataclass
class WizardState:
    """What the operator has already established for this session."""

    artifacts_root: str = ""

    def options(self, **overrides: object):
        """Feeds options for the artifacts root this session is using."""
        return feeds_options(
            artifacts_root=self.artifacts_root or None,
            **overrides,  # type: ignore[arg-type]
        )


def confirm_network(prompt: str = NETWORK_PROMPT) -> bool:
    """Ask before a live SEC request. Defaults to no."""
    return prompt_text(prompt.strip(), "n").strip().lower() in ("y", "yes")


def render_session_header(state: WizardState) -> str:
    """One line describing the ledger this session is pointed at."""
    paths = resolve_feeds_paths(state.artifacts_root or None)
    tip = ledger_tip(paths)
    return f"ledger tip: {tip}" if tip else "no ledger published"


def run_live(state: WizardState) -> None:
    if not confirm_network():
        print("cancelled; nothing was fetched")
        return
    cmd_run(state.options())


def backfill(state: WizardState) -> None:
    start = prompt_text("Start month (YYYY-MM)", "").strip()
    end = prompt_text("End month (YYYY-MM)", start).strip()
    if not start or not end:
        print("cancelled; a month range is required")
        return
    try:
        options = state.options(start=parse_month(start), end=parse_month(end))
    except ValueError as exc:
        print(f"cancelled; {exc}")
        return
    if not confirm_network():
        print("cancelled; nothing was fetched")
        return
    cmd_backfill(options)


def status(state: WizardState) -> None:
    cmd_status(state.options())


def open_feeds_dag_console(state: WizardState) -> None:
    """Launch the interactive DAG lifecycle console for ledger snapshots."""
    from edgar_sec.infra.storage.dag.menu import DAGMenuConfig, run_dag_menu
    from .specs import FEED_RELATION_SPECS

    config = DAGMenuConfig(
        snapshots_root=lambda: (
            resolve_feeds_paths(state.artifacts_root or None).snapshots_root
        ),
        title="Feeds Ledger Snapshot DAG Console",
        specs=FEED_RELATION_SPECS,
    )
    run_dag_menu(config)


def build_operator_menu(state: WizardState | None = None) -> tuple[MenuAction, ...]:
    """Build the operator actions, bound to this session's state."""
    session = state if state is not None else WizardState()
    return build_menu(
        menu_action("Run live feeds", lambda: run_live(session)),
        menu_action("Backfill monthly archives", lambda: backfill(session)),
        menu_action("Ledger status", lambda: status(session)),
        menu_action(
            "Snapshot DAG console (inspect, branches, tags)",
            lambda: open_feeds_dag_console(session),
            key="p",
        ),
    )


def main(argv: list[str] | None = None) -> int:
    """Operator entrypoint: interactive by default, CLI when given a command."""
    state = WizardState()
    return operator_entrypoint(
        MENU_TITLE,
        build_operator_menu(state),
        cli_main,
        argv,
        before_menu=lambda: render_session_header(state),
    )


if __name__ == "__main__":
    sys.exit(main())
