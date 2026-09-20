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
from .core.partition_handoff import discover_finalized_partitions

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
        locs = (
            plan.get("unique_locators_count") or plan.get("active_targets_count") or "?"
        )
        print(f"  Target Plan: {plan['plan_id']} ({locs} locators) -> {plan['path']}")
        raw = _read(f"  Plan directory [{plan['path']}]: ", plan["path"])
        return raw

    print("  Discovered Phase 02 Target Plans:")
    for idx, plan in enumerate(plans, start=1):
        locs = (
            plan.get("unique_locators_count") or plan.get("active_targets_count") or "?"
        )
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
    pub = phase_paths.published_dataset("partition_artifacts", "sqlite")
    if pub.is_file():
        return str(pub)

    runs = phase_paths.runs_root
    if runs.is_dir():
        dbs = sorted(runs.glob("*/*/partition-*.sqlite"))
        if dbs:
            return str(dbs[0])
    return ""


def _finalized_run_candidates() -> list[dict]:
    """Discover run namespaces with finalized partition handoffs."""
    phase_paths = resolve_paths("webpage_storage")
    root = phase_paths.project.partition_artifacts_root(
        "webpage_storage", "partition_artifacts"
    )
    candidates = []
    if not root.is_dir():
        return candidates
    for entry in sorted(
        (item for item in root.iterdir() if item.is_dir()), key=lambda item: item.name
    ):
        run_id = entry.name
        try:
            paths = discover_finalized_partitions(run_id, validate=False)
        except ValueError:
            continue
        if not paths:
            continue
        meta_path = phase_paths.run(run_id).run_root / "run_metadata.json"
        metadata = {}
        if meta_path.is_file():
            with suppress(Exception):
                from defs.storage import load_json

                metadata = load_json(meta_path)
        expected = int(metadata.get("partition_count") or 0)
        partition_ids = []
        for path in paths:
            try:
                partition_ids.append(int(path.stem.split("-")[-1]))
            except ValueError:
                continue
        complete = bool(
            expected and sorted(partition_ids) == list(range(1, expected + 1))
        )
        candidates.append(
            {
                "run_id": run_id,
                "plan_id": metadata.get("plan_id"),
                "partition_count": expected,
                "partition_ids": sorted(partition_ids),
                "complete": complete,
            }
        )
    return sorted(candidates, key=lambda item: (not item["complete"], item["run_id"]))


def _select_finalized_run() -> str | None:
    candidates = _finalized_run_candidates()
    complete = [item for item in candidates if item["complete"]]
    if not candidates:
        print("  no finalized partition runs found")
        return None
    print("  Finalized partition runs:")
    for index, item in enumerate(candidates, start=1):
        state = "complete" if item["complete"] else "incomplete"
        print(
            f"    {index}. {item['run_id']} ({state}; "
            f"partitions {item['partition_ids'] or 'none'})"
        )
    default_index = next(
        (index for index, item in enumerate(candidates, start=1) if item["complete"]), 1
    )
    choice = _read(f"  Select run [{default_index}]: ", str(default_index))
    try:
        index = int(choice) - 1
        if 0 <= index < len(candidates):
            selected = candidates[index]
        else:
            selected = candidates[default_index - 1]
    except ValueError:
        selected = candidates[default_index - 1]
    if not selected["complete"] and complete:
        print(
            "  selected run is incomplete; snapshot merge will report missing partitions"
        )
    return selected["run_id"]


def _usage() -> str:
    return (
        "usage: python run.py webpage-storage            interactive menu\n"
        "       python run.py webpage-storage run --plan-dir <p> --mode fixture\n"
        "       python run.py webpage-storage preview --plan-dir <p>\n"
        "       python run.py webpage-storage merge-to-snapshot --partition-db <path>\n"
        "       python run.py webpage-storage vacuum --all\n"
        "       python run.py webpage-storage status --database <path>"
    )


def append_fixture(argv: list[str] | None = None) -> int:
    """Convenience wrapper that forwards append requests to ``fill-fixture``."""
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] != "fill-fixture":
        args = ["fill-fixture", *args]
    return cli_main(args)


def interactive_menu() -> int:
    default_workers = str(max(1, derive_resources().workers))

    while True:
        print("\nPhase 2.5: Webpage Storage and normalized snapshots")
        print("  1. Preview target plan")
        print("  2. Run acquisition (fixture mode)")
        print("  3. Run acquisition (production mode - live SEC)")
        print("  4. Fill / update offline fixture from live SEC")
        print("  5. Append fixture cache")
        print("  6. Show status")
        print("  7. Merge finalized partitions to snapshot")
        print("  8. Vacuum all snapshots")
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
                cli_main(
                    [
                        "run",
                        "--plan-dir",
                        plan_dir,
                        "--mode",
                        "fixture",
                        "--workers",
                        default_workers,
                    ]
                )
        elif choice == "3":
            plan_dir = _select_target_plan()
            if plan_dir:
                cli_main(
                    [
                        "run",
                        "--plan-dir",
                        plan_dir,
                        "--mode",
                        "production",
                        "--workers",
                        default_workers,
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
            plan_dir = _select_target_plan()
            if plan_dir:
                def_fix_id = f"fix-{Path(plan_dir).name[:8]}"
                fixture_id = _read(f"  Fixture ID [{def_fix_id}]: ", def_fix_id)

                limit = _read("  Limit (blank for all): ", "")
                retry = _read("  Retry previous failures? [y/N]: ", "N")
                cmd = [
                    "fill-fixture",
                    "--plan-dir",
                    plan_dir,
                    "--fixture-id",
                    fixture_id,
                    "--workers",
                    default_workers,
                ]
                if limit:
                    cmd.extend(["--limit", limit])
                if retry.lower() in ("y", "yes"):
                    cmd.append("--retry-failures")
                append_fixture(cmd)
        elif choice == "6":
            candidates = _finalized_run_candidates()
            default_run = candidates[0]["run_id"] if candidates else ""
            run_id = _read(
                f"  Run ID [{default_run}]: " if default_run else "  Run ID: ",
                default_run,
            )
            if run_id:
                cli_main(["status", "--run-id", run_id])
            else:
                print("  no finalized run specified or found")
        elif choice == "7":
            run_id = _select_finalized_run()
            if run_id:
                cli_main(["merge-to-snapshot", "--run-id", run_id])
        elif choice == "8":
            cli_main(["vacuum", "--all", "--workers", default_workers])
        else:
            print("  unknown choice")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("-h", "--help"):
        print(_usage())
        return 0
    if argv and argv[0] == "append":
        return append_fixture(argv[1:])
    if not argv:
        try:
            return interactive_menu()
        except KeyboardInterrupt:
            print("\ninterrupted")
            return 130
    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
