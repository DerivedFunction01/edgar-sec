"""Interactive terminal operator for the datasets pipeline.

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
from .commands.population import cmd_population
from .commands.status import cmd_status
from .commands.verify import cmd_verify
from .options import datasets_options
from .paths import resolve_datasets_paths
from .publish import store_tip

__all__ = [
    "WizardState",
    "build_operator_menu",
    "confirm_network",
    "main",
    "render_session_header",
]

MENU_TITLE = "SEC Datasets"

NETWORK_PROMPT = "This contacts SEC over the network. Continue? (y/N) "


@dataclass
class WizardState:
    """What the operator has already established for this session."""

    artifacts_root: str = ""

    def options(self, **overrides: object):
        """Datasets options for the artifacts root this session is using."""
        return datasets_options(
            artifacts_root=self.artifacts_root or None,
            **overrides,  # type: ignore[arg-type]
        )


def confirm_network(prompt: str = NETWORK_PROMPT) -> bool:
    """Ask before a live SEC request. Defaults to no."""
    return prompt_text(prompt.strip(), "n").strip().lower() in ("y", "yes")


def render_session_header(state: WizardState) -> str:
    """One line describing the index this session is pointed at."""
    paths = resolve_datasets_paths(state.artifacts_root or None)
    tip = store_tip(paths)
    return f"index tip: {tip}" if tip else "no index published"


def population(state: WizardState) -> None:
    if not confirm_network():
        print("cancelled; nothing was fetched")
        return
    cmd_population(state.options())


def status(state: WizardState) -> None:
    cmd_status(state.options())


def verify(state: WizardState) -> None:
    cmd_verify(state.options())


def build_operator_menu(state: WizardState | None = None) -> tuple[MenuAction, ...]:
    """Build the operator actions, bound to this session's state."""
    session = state if state is not None else WizardState()
    return build_menu(
        menu_action("Load BDC population register", lambda: population(session)),
        menu_action("Verify store (oracle pass)", lambda: verify(session)),
        menu_action("Store status", lambda: status(session)),
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
