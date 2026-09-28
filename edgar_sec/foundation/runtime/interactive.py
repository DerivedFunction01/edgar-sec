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
) -> int:
    """Run an interactive action loop until user selects exit."""
    action_map = {a.key.lower(): a for a in actions}

    while True:
        print(f"\n{title}")
        for a in actions:
            print(f"  {a.key}. {a.label}")
        print(f"  {exit_key}. Exit")

        choice = (
            prompt_text("\nChoice", default=actions[0].key if actions else exit_key)
            .strip()
            .lower()
        )
        if choice == exit_key or not choice:
            return 0

        action = action_map.get(choice)
        if action is not None:
            try:
                action.callback()
            except KeyboardInterrupt:
                print("\nAction cancelled by user.")
            except (RuntimeError, ValueError, OSError) as exc:
                print(f"\nError executing action '{action.label}': {exc}")
        else:
            print("Invalid choice, please select again.")


def operator_entrypoint(
    title: str,
    menu: tuple[MenuAction, ...] | list[MenuAction],
    cli_main: Callable[[list[str]], int],
    argv: list[str] | None = None,
) -> int:
    """Dispatch a pipeline operator: menu with no arguments, CLI otherwise.

    Every pipeline operator needs this same entrypoint policy, so it is stated
    once here instead of restated per pipeline. The pipeline supplies its title,
    its menu, and its CLI entrypoint; nothing else about its behavior is
    assumed. Kept in this module because it is pure presentation wiring -- it
    decides which surface to show, never what a command does.
    """
    args = sys.argv[1:] if argv is None else argv
    if not args:
        return run_interactive_menu(title, menu, exit_key="0")
    return cli_main(args)


__all__ = [
    "MenuAction",
    "operator_entrypoint",
    "prompt_choice",
    "prompt_text",
    "run_interactive_menu",
]
