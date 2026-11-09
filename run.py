"""Root interactive launcher and CLI dispatcher for edgar_sec.

Holds both Layer 4 pipelines and Layer 5 apps, hence ``LauncherEntry``.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from edgar_sec.foundation.runtime.interactive import MenuSeparator


@dataclass(frozen=True)
class LauncherEntry:
    id: str
    label: str
    description: str
    module: str
    group: str


ENTRIES: tuple[LauncherEntry, ...] = (
    LauncherEntry(
        id="cohort",
        label="Cohort Management",
        description="Manage, import, query, and combine registrant cohorts",
        module="edgar_sec.pipelines.cohort.cli",
        group="Pipelines",
    ),
    LauncherEntry(
        id="metadata",
        label="Metadata Sync",
        description="SEC submissions metadata extraction and partition sync",
        module="edgar_sec.pipelines.metadata_sync.operator",
        group="Pipelines",
    ),
    LauncherEntry(
        id="feeds",
        label="Structured Disclosure Feeds",
        description="Structured-disclosure RSS feed ledger: live run, archive backfill, status",
        module="edgar_sec.pipelines.feeds.operator",
        group="Pipelines",
    ),
    LauncherEntry(
        id="datasets",
        label="SEC Datasets",
        description="Data-research dataset imports (BDC, N-MFP, MFRR oracles): import, population, verify, status",
        module="edgar_sec.pipelines.datasets.operator",
        group="Pipelines",
    ),
    LauncherEntry(
        id="filing-catalog",
        label="Filing Catalog",
        description="Offline DuckDB catalog materialization and target planning",
        module="edgar_sec.pipelines.filing_catalog.operator",
        group="Pipelines",
    ),
    LauncherEntry(
        id="inventory",
        label="Document Inventory",
        description="Discover fixtures and review SEC index pages",
        module="edgar_sec.pipelines.document_inventory.operator",
        group="Pipelines",
    ),
    LauncherEntry(
        id="planning",
        label="Document Planning",
        description="Resolve filing targets from published catalog and inventory evidence",
        module="edgar_sec.pipelines.document_planning.operator",
        group="Pipelines",
    ),
    LauncherEntry(
        id="acquisition",
        label="Document Acquisition",
        description="Project, acquire, and process selected document targets",
        module="edgar_sec.pipelines.document_acquisition.operator",
        group="Pipelines",
    ),
    LauncherEntry(
        id="xbrl",
        label="XBRL Semantic Review",
        description="XBRL solver, counter-solver, and review & staging console",
        module="edgar_sec.pipelines.xbrl_review.operator",
        group="Pipelines",
    ),
    LauncherEntry(
        id="viewer",
        label="Dataset Viewer",
        description="Read-only browser and SQL console over published artifacts",
        module="edgar_sec.apps.viewer.cli",
        group="Apps & Consoles",
    ),
    LauncherEntry(
        id="fetch",
        label="Filing Runner & Fetch",
        description="Unified end-to-end filing acquisition and DataFrame extraction",
        module="edgar_sec.apps.client.operator",
        group="Apps & Consoles",
    ),
    LauncherEntry(
        id="dag",
        label="Snapshot DAG Console",
        description="Interactive DAG lineage, swimlane graphs, tags, branches, and maintenance",
        module="edgar_sec.infra.storage.dag.operator",
        group="Apps & Consoles",
    ),
)


def _build_menu_items() -> tuple[LauncherEntry | MenuSeparator, ...]:
    items: list[LauncherEntry | MenuSeparator] = []
    seen: set[str] = set()
    for entry in ENTRIES:
        if entry.group not in seen:
            seen.add(entry.group)
            items.append(MenuSeparator(entry.group))
        items.append(entry)
    return tuple(items)


_MENU_ITEMS = _build_menu_items()


def _launch(entry: LauncherEntry) -> None:
    import runpy

    try:
        runpy.run_module(entry.module, run_name="__main__", alter_sys=True)
    except KeyboardInterrupt:
        print("\nAction cancelled by user.")
    except SystemExit as exc:
        if exc.code not in (None, 0):
            print(f"\nError executing action '{entry.label}': {exc!r}")
    except Exception as exc:  # noqa: BLE001 - the launcher must outlive one entry
        print(f"\nError executing action '{entry.label}': {exc!r}")


def _menu() -> int:
    print("\n==========================================")
    print("   EDGAR SEC Launcher (v2)                ")
    print("==========================================")
    while True:
        idx = 0
        for item in _MENU_ITEMS:
            if isinstance(item, MenuSeparator):
                if item.title:
                    prefix = f"── {item.title} "
                    print(prefix + "─" * max(0, 64 - len(prefix)))
                else:
                    print()
                continue
            idx += 1
            print(f"  {idx}. {item.label} - {item.description}")
        print("  0. Exit")
        try:
            raw = input("\nChoice [0]: ").strip()
        except EOFError:
            return 0
        except KeyboardInterrupt:
            print()
            return 0
        if not raw or raw == "0":
            return 0
        try:
            choice = int(raw)
        except ValueError:
            print("Invalid choice, please select again.")
            continue
        if not 1 <= choice <= len(ENTRIES):
            print("Invalid choice, please select again.")
            continue
        _launch(ENTRIES[choice - 1])


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        return _menu()
    if args[0] in ("-h", "--help"):
        print("Usage: python run.py [<entry> [arguments...]]")
        print()
        print("With no entry, opens the interactive menu, which loops until")
        print("Exit is chosen and returns to the menu after each entry runs.")
        print("With an entry, runs that entry directly: every argument after")
        print("the entry name is forwarded to the entry unchanged.")
        print()
        print("Options:")
        print("  --list - list the available entries")
        print("  --help - show this help")
        print()
        print("Available entries:")
        for entry in ENTRIES:
            print(f"  {entry.id} - {entry.label}: {entry.description}")
        return 0
    if args[0] == "--list":
        for entry in ENTRIES:
            print(f"{entry.id}: {entry.label}")
        return 0

    cmd = args[0]
    for entry in ENTRIES:
        if entry.id == cmd:
            import runpy

            sys.argv = [entry.module, *args[1:]]
            runpy.run_module(entry.module, run_name="__main__", alter_sys=True)
            return 0

    print(
        f"Unknown pipeline: '{cmd}'. Run 'python run.py --list' to see available pipelines."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
