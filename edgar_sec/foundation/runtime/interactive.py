"""Generic terminal prompt and interactive menu utilities."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from .settings.interactive import DEFAULT_PAGE_SIZE


@dataclass(frozen=True, slots=True)
class MenuAction:
    """One selectable menu action in an interactive terminal loop."""

    key: str
    label: str
    callback: Callable[[], Any]


@dataclass(frozen=True, slots=True)
class MenuSeparator:
    title: str = ""


def menu_action(
    label: str,
    callback: Callable[[], Any],
    *,
    key: str | None = None,
) -> MenuAction:
    """Create a menu action with an optional explicit key override."""
    return MenuAction(key=key or "", label=label, callback=callback)


def assign_menu_keys(
    actions: Sequence[MenuAction | MenuSeparator],
    *,
    exit_key: str = "0",
    start: int = 1,
) -> tuple[MenuAction, ...]:
    """Auto-assign sequential numeric keys to unkeyed actions, preserving explicit keys."""
    reserved = {exit_key.lower()}
    for a in actions:
        if isinstance(a, MenuAction) and a.key:
            reserved.add(a.key.lower())

    result: list[MenuAction | MenuSeparator] = []
    next_num = start
    for a in actions:
        if isinstance(a, MenuSeparator):
            result.append(a)
            continue
        if a.key:
            result.append(a)
        else:
            while str(next_num) in reserved:
                next_num += 1
            result.append(
                MenuAction(key=str(next_num), label=a.label, callback=a.callback)
            )
            next_num += 1

    return tuple(result)


def build_menu(
    *actions: MenuAction | MenuSeparator,
    exit_key: str = "0",
) -> tuple[MenuAction | MenuSeparator, ...]:
    """Ergonomic factory for building an auto-keyed MenuAction tuple."""
    return assign_menu_keys(actions, exit_key=exit_key)


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


@dataclass(frozen=True, slots=True)
class PickItem:
    """One selectable item in a paginated pick-list."""

    key: str
    label: str
    value: Any


def prompt_paginated_choice(
    items: Sequence[PickItem],
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    prompt_label: str = "Choice",
    default: PickItem | str | None = None,
) -> PickItem | None:
    """Interactively select an item with pagination, filtering, and a default.

    A blank answer while the default is visible returns it.
    """
    if not items:
        print("No items available.")
        return None

    def _default_index() -> int | None:
        target = default.key if isinstance(default, PickItem) else default
        if target is None:
            return None
        if active_filter:
            q = active_filter.lower()
            for i, it in enumerate(items):
                if q in it.key.lower() or q in it.label.lower():
                    if it.key == target:
                        return i
            return None
        for i, it in enumerate(items):
            if it.key == target:
                return i
        return None

    active_filter = ""
    default_idx = _default_index()
    offset = 0
    if default_idx is not None and not active_filter:
        offset = max(0, (default_idx // page_size) * page_size)

    while True:
        if active_filter:
            q = active_filter.lower()
            filtered = [
                it for it in items if q in it.key.lower() or q in it.label.lower()
            ]
        else:
            filtered = list(items)

        total = len(filtered)
        if total == 0:
            print(f"No items match filter '{active_filter}'. [c]lear to reset.")
            ans = prompt_text("[c]lear filter or [q]uit", "c").strip()
            if ans.lower() == "c":
                active_filter = ""
                offset = 0
            else:
                return None
            continue

        if offset >= total:
            offset = max(0, ((total - 1) // page_size) * page_size)

        page_items = filtered[offset : offset + page_size]
        current_page = (offset // page_size) + 1
        total_pages = max(1, (total + page_size - 1) // page_size)
        is_default_page = (
            default_idx is not None
            and not active_filter
            and offset == default_idx // page_size * page_size
        )

        filter_banner = f" | Filter: '{active_filter}'" if active_filter else ""
        print(
            f"\nShowing {offset + 1}-{offset + len(page_items)} of {total} items "
            f"(Page {current_page}/{total_pages}{filter_banner}):"
        )
        for idx, it in enumerate(page_items, start=1):
            marker = " (default)" if is_default_page and it.key == default.key else ""
            print(f"  [{idx}] {it.label}{marker}")

        nav_options: list[str] = [f"1-{len(page_items)}"]
        if current_page < total_pages:
            nav_options.append("[n]ext")
        if current_page > 1:
            nav_options.append("[p]rev")
        if active_filter:
            nav_options.append("[c]lear filter")
        nav_options.append("[q]uit")

        prompt_msg = f"{prompt_label} ({', '.join(nav_options)} or type text to filter)"
        choice = prompt_text(prompt_msg, "").strip()

        if not choice:
            if (
                is_default_page
                and isinstance(default, PickItem)
                and default in page_items
            ):
                return default
            return None
        if choice.lower() == "q":
            return None
        if choice.lower() == "n":
            if current_page < total_pages:
                offset += page_size
            continue
        if choice.lower() == "p":
            if current_page > 1:
                offset -= page_size
            continue
        if choice.lower() == "c":
            active_filter = ""
            offset = 0
            continue
        if choice.isdigit():
            val = int(choice)
            if 1 <= val <= len(page_items):
                return page_items[val - 1]
            print(f"Selection must be between 1 and {len(page_items)}.")
            continue

        active_filter = choice
        offset = 0


def run_interactive_menu(
    title: str,
    actions: tuple[MenuAction | MenuSeparator, ...] | list[MenuAction | MenuSeparator],
    exit_key: str = "0",
    *,
    interrupted_message: str | None = None,
    before_menu: Callable[[], str | None] | None = None,
) -> int:
    """Run an interactive action loop until the user selects exit.

    A blank answer re-renders rather than defaulting to the first action, which may mutate;
    ``before_menu`` runs per render and a failure inside it still draws the menu.
    """
    action_map = {a.key.lower(): a for a in actions if isinstance(a, MenuAction)}

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
            if isinstance(a, MenuSeparator):
                if a.title:
                    prefix = f"── {a.title} "
                    print(prefix + "─" * max(0, 64 - len(prefix)))
                else:
                    print()
            else:
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
    menu: tuple[MenuAction | MenuSeparator, ...] | list[MenuAction | MenuSeparator],
    cli_main: Callable[[list[str]], int],
    argv: list[str] | None = None,
    *,
    interrupted_message: str | None = None,
    before_menu: Callable[[], str | None] | None = None,
) -> int:
    """Dispatch a pipeline operator: menu with no arguments, CLI otherwise.

    ``before_menu`` is consulted only on the interactive path; an argument-dispatched
    command must not resolve or print session state, since there is no session.
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
    "MenuSeparator",
    "PickItem",
    "assign_menu_keys",
    "build_menu",
    "menu_action",
    "operator_entrypoint",
    "prompt_choice",
    "prompt_paginated_choice",
    "prompt_text",
    "run_interactive_menu",
]
