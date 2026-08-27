"""Root launcher over the static registry (``defs.runtime.registry``).

Interactive menu:

    python run.py

Direct dispatch (all flags after the id pass through to the target module):

    python run.py viewer --port 8501
    python run.py metadata
    python run.py --list

The dispatcher owns no phase behavior: it resolves an entry, patches
``sys.argv``, and executes the registered module in-process exactly as
``python -m <module>`` would, propagating the child's exit code.
"""

from __future__ import annotations

import json
import runpy
import sys
from dataclasses import asdict

from defs.runtime.registry import ENTRIES, LauncherEntry, find_entry

_PROG = "run.py"


def _dispatch(entry: LauncherEntry, args: list[str]) -> int:
    """Run the entry's module with ``args`` as its argv; return its code."""
    previous_argv = sys.argv
    sys.argv = [entry.module, *args]
    try:
        runpy.run_module(entry.module, run_name="__main__", alter_sys=True)
    except SystemExit as exc:  # child requested exit (argparse help, errors)
        code = exc.code
        if code is None:
            return 0
        if isinstance(code, int):
            return code
        print(code)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130
    finally:
        sys.argv = previous_argv
    return 0


def _menu() -> int:
    print("EDGAR pipeline launcher")
    while True:
        for index, entry in enumerate(ENTRIES, start=1):
            print(f"  {index}. {entry.label} - {entry.description}")
        print("  0. Exit")
        try:
            raw = input("\nChoice [0]: ").strip()
        except EOFError:
            return 0
        if not raw or raw == "0":
            return 0
        entry: LauncherEntry | None = None
        if raw.isdigit() and 1 <= int(raw) <= len(ENTRIES):
            entry = ENTRIES[int(raw) - 1]
        if entry is None:
            entry = find_entry(raw)
        if entry is None:
            print(f"  unknown choice: {raw}")
            continue
        # Menu launches use the entry's default arguments only; pass custom
        # flags through direct dispatch instead.
        return _dispatch(entry, [])


def _usage() -> str:
    lines = [
        f"usage: python {_PROG}                 interactive menu",
        f"       python {_PROG} <entry> [args...]   direct dispatch",
        f"       python {_PROG} --list          print entries as JSON",
        "",
        "Entries:",
    ]
    lines.extend(
        f"  {entry.id:<10} {entry.label} - {entry.description}"
        for entry in ENTRIES
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        return _menu()
    first = args[0]
    if first in ("-h", "--help"):
        print(_usage())
        return 0
    if first == "--list":
        print(json.dumps([asdict(entry) for entry in ENTRIES], indent=2))
        return 0
    entry = find_entry(first)
    if entry is None:
        valid = ", ".join(item.id for item in ENTRIES)
        print(
            f"error: unknown entry {first!r} (valid: {valid})", file=sys.stderr
        )
        return 2
    return _dispatch(entry, args[1:])


if __name__ == "__main__":
    sys.exit(main())
