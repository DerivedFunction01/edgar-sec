"""Interactive Phase 2.5 runner and launcher module.

Selecting ``Phase 2.5: Webpage Storage`` from ``python run.py`` opens a phase
menu. Explicit subcommands are forwarded verbatim to the canonical CLI so
automation keeps one contract with the command surface.
"""

from __future__ import annotations

import builtins
import logging
import sys

from .cli import main as cli_main

log = logging.getLogger("webpage_storage.run")


def _read(prompt: str, default: str = "") -> str:
    try:
        return builtins.input(prompt).strip() or default
    except EOFError:
        return default


def _usage() -> str:
    return (
        "usage: python run.py webpage-storage            interactive menu\n"
        "       python run.py webpage-storage run --plan-dir <p> --mode fixture\n"
        "       python run.py webpage-storage preview --plan-dir <p>\n"
        "       python run.py webpage-storage status --database <path>"
    )


def interactive_menu() -> int:
    while True:
        print("\nPhase 2.5: Webpage Storage (raw document acquisition)")
        print("  1. Preview target plan")
        print("  2. Run acquisition (fixture mode)")
        print("  3. Show status")
        print("  0. Exit")
        choice = _read("\nChoice [0]: ", "0")
        if choice == "0":
            return 0
        if choice == "1":
            plan_dir = _read("Plan dir: ")
            if plan_dir:
                cli_main(["preview", "--plan-dir", plan_dir])
        elif choice == "2":
            plan_dir = _read("Plan dir: ")
            if plan_dir:
                cli_main(["run", "--plan-dir", plan_dir, "--mode", "fixture"])
        elif choice == "3":
            database = _read("Database path: ")
            if database:
                cli_main(["status", "--database", database])
        else:
            print("  unknown choice")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help"):
        print(_usage())
        return 0
    if not argv:
        try:
            return interactive_menu()
        except KeyboardInterrupt:
            print("\ninterrupted")
            return 130
    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
