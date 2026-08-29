"""Interactive Phase 2.5 runner and launcher module.

Selecting ``Phase 2.5: Webpage Storage`` from ``python run.py`` opens a phase
menu. Explicit subcommands are forwarded verbatim to the canonical CLI so
automation keeps one contract with the command surface.
"""

from __future__ import annotations

import builtins
import importlib
import logging
import sys
from contextlib import suppress
from pathlib import Path

from defs.runtime.paths import resolve_paths
from defs.runtime.resources import derive_resources

from .cli import main as cli_main

log = logging.getLogger("webpage_storage.run")


def _read(prompt: str, default: str = "") -> str:
    try:
        return builtins.input(prompt).strip() or default
    except EOFError:
        return default


def _select_target_plan() -> str | None:
    """Auto-discover Phase 02 target plans or prompt for a path."""
    plans = []
    with suppress(ImportError, OSError, ValueError):
        discovery = importlib.import_module(
            "phases.02_filing_extraction.core.discovery"
        )
        plans = discovery.discover_plans()

    if not plans:
        raw = _read("Phase 02 Target Plan directory: ")
        return raw or None

    if len(plans) == 1:
        plan = plans[0]
        locs = plan.get("unique_locators") or plan.get("active_targets") or "?"
        print(f"  Target Plan: {plan['plan_id']} ({locs} locators) -> {plan['path']}")
        raw = _read(f"  Plan directory [{plan['path']}]: ", plan["path"])
        return raw

    print("  Discovered Phase 02 Target Plans:")
    for idx, plan in enumerate(plans, start=1):
        locs = plan.get("unique_locators") or plan.get("active_targets") or "?"
        print(f"    {idx}. {plan['plan_id']} ({locs} locators)")

    choice = _read(f"  Select plan [1-{len(plans)}] [1]: ", "1")
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(plans):
            return plans[idx]["path"]
    except ValueError:
        pass
    return plans[0]["path"]


def _default_partition_db() -> str:
    """Find latest published or transient partition database."""
    phase_paths = resolve_paths("webpage_storage")
    pub = phase_paths.published_dataset("filing_documents", "sqlite")
    if pub.is_file():
        return str(pub)

    runs = phase_paths.runs_root
    if runs.is_dir():
        dbs = sorted(runs.glob("*/*/partition-*.sqlite"))
        if dbs:
            return str(dbs[0])
    return ""


def _usage() -> str:
    return (
        "usage: python run.py webpage-storage            interactive menu\n"
        "       python run.py webpage-storage run --plan-dir <p> --mode fixture\n"
        "       python run.py webpage-storage preview --plan-dir <p>\n"
        "       python run.py webpage-storage status --database <path>"
    )


def interactive_menu() -> int:
    default_workers = str(max(1, derive_resources().workers))

    while True:
        print("\nPhase 2.5: Webpage Storage (raw document acquisition)")
        print("  1. Preview target plan")
        print("  2. Run acquisition (fixture mode)")
        print("  3. Run acquisition (production mode - live SEC)")
        print("  4. Fill / update offline fixture from live SEC")
        print("  5. Show status")
        print("  0. Exit")
        choice = _read("\nChoice [0]: ", "0")
        if choice == "0":
            return 0
        if choice == "1":
            plan_dir = _select_target_plan()
            if plan_dir:
                cli_main(["preview", "--plan-dir", plan_dir])
        elif choice == "2":
            plan_dir = _select_target_plan()
            if plan_dir:
                workers = _read(f"  Workers [{default_workers}]: ", default_workers)
                cli_main(
                    [
                        "run",
                        "--plan-dir",
                        plan_dir,
                        "--mode",
                        "fixture",
                        "--workers",
                        workers,
                    ]
                )
        elif choice == "3":
            plan_dir = _select_target_plan()
            if plan_dir:
                workers = _read(f"  Workers [{default_workers}]: ", default_workers)
                cli_main(
                    [
                        "run",
                        "--plan-dir",
                        plan_dir,
                        "--mode",
                        "production",
                        "--workers",
                        workers,
                    ]
                )
        elif choice == "4":
            plan_dir = _select_target_plan()
            if plan_dir:
                def_fix_id = f"fix-{Path(plan_dir).name[:8]}"
                fixture_id = _read(f"  Fixture ID [{def_fix_id}]: ", def_fix_id)
                limit = _read("  Limit (blank for all): ", "")
                cmd = [
                    "fill-fixture",
                    "--plan-dir",
                    plan_dir,
                    "--fixture-id",
                    fixture_id,
                ]
                if limit:
                    cmd.extend(["--limit", limit])
                cli_main(cmd)
        elif choice == "5":
            def_db = _default_partition_db()
            prompt = f"  Database path [{def_db}]: " if def_db else "  Database path: "
            database = _read(prompt, def_db)
            if database:
                cli_main(["status", "--database", database])
            else:
                print("  no database specified or found")
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
