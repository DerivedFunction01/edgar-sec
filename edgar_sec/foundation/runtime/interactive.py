"""Generic terminal prompt and interactive menu utilities."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class MenuAction:
    """One selectable menu action in an interactive terminal loop."""

    key: str
    label: str
    callback: Callable[[], Any]


def prompt_text(prompt: str, default: str = "") -> str:
    """Prompt user for terminal input with an optional default value."""
    p_str = f"{prompt} [{default}]: " if default else f"{prompt}: "
    try:
        raw = input(p_str).strip()
        return raw or default
    except EOFError:
        return default


def prompt_choice(
    title: str,
    choices: list[tuple[str, str]],
    default: str = "",
) -> str:
    """Display a numbered or keyed choice menu and return the selected key."""
    print(f"\n{title}")
    valid_keys = set()
    for key, label in choices:
        valid_keys.add(key.lower())
        print(f"  {key}. {label}")

    while True:
        res = prompt_text("Choice", default).strip().lower()
        if res in valid_keys:
            return res
        print(
            f"Invalid option '{res}', please select from: {', '.join(sorted(valid_keys))}"
        )


def run_interactive_menu(
    title: str,
    actions: tuple[MenuAction, ...] | list[MenuAction],
    exit_key: str = "0",
    *,
    interrupted_message: str | None = None,
    before_menu: Callable[[], str | None] | None = None,
) -> int:
    """Run an interactive action loop until user selects exit.

    A blank answer re-renders the menu rather than running the first action:
    defaulting it would let a stray Return silently start whichever action is
    listed first, which is not harmless for a mutating command.

    Any exception from an action is reported with its type and the loop
    continues, because a wizard that dies on an unexpected error loses the
    session the operator was holding, and a hidden failure class is harder to
    diagnose than the failure.

    ``interrupted_message`` states what survives an interrupt, which is phase
    knowledge this module cannot have. ``before_menu`` runs once per render and
    may return a header line showing the state a pipeline resolved for this
    session; a failure inside it is reported and the menu is still drawn, so a
    broken header cannot strand the operator with no way back.
    """
    action_map = {a.key.lower(): a for a in actions}

    while True:
        if before_menu is not None:
            try:
                header = before_menu()
                if header:
                    print(f"\n{header}")
            except Exception as exc:  # noqa: BLE001 - a header must not hide the menu
                print(f"\nCould not resolve session state: {exc!r}")

        print(f"\n{title}")
        for a in actions:
            print(f"  {a.key}. {a.label}")
        print(f"  {exit_key}. Exit")

        raw = prompt_text("\nChoice", "").strip()
        if raw == exit_key:
            return 0
        if not raw:
            continue
        choice = raw.lower()

        action = action_map.get(choice)
        if action is None:
            print("Invalid choice, please select again.")
            continue
        try:
            action.callback()
        except KeyboardInterrupt:
            print(f"\n{interrupted_message or 'Action cancelled by user.'}")
        except Exception as exc:  # noqa: BLE001 - a wizard must outlive one failure
            print(f"\nError executing action '{action.label}': {exc!r}")


def operator_entrypoint(
    title: str,
    menu: tuple[MenuAction, ...] | list[MenuAction],
    cli_main: Callable[[list[str]], int],
    argv: list[str] | None = None,
    *,
    interrupted_message: str | None = None,
    before_menu: Callable[[], str | None] | None = None,
) -> int:
    """Dispatch a pipeline operator: menu with no arguments, CLI otherwise.

    The pipeline supplies its title, its menu, and its CLI entrypoint; nothing
    else about its behavior is assumed.

    ``before_menu`` is only consulted on the interactive path. A command
    dispatched with arguments must not resolve or print session state, because
    there is no session: the arguments already name what the command acts on.
    """
    args = sys.argv[1:] if argv is None else argv
    if not args:
        return run_interactive_menu(
            title,
            menu,
            exit_key="0",
            interrupted_message=interrupted_message,
            before_menu=before_menu,
        )
    return cli_main(args)


__all__ = [
    "MenuAction",
    "operator_entrypoint",
    "prompt_choice",
    "prompt_text",
    "run_interactive_menu",
]
