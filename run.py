"""Root interactive launcher and CLI dispatcher for edgar_sec.

Holds both Layer 4 pipelines and Layer 5 apps, hence ``LauncherEntry``.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class LauncherEntry:
    id: str
    label: str
    description: str
    module: str


ENTRIES: tuple[LauncherEntry, ...] = (
    LauncherEntry(
        id="cohort",
        label="Cohort Management",
        description="Manage, import, query, and combine registrant cohorts",
        module="edgar_sec.pipelines.cohort.cli",
    ),
    LauncherEntry(
        id="metadata",
        label="Metadata Sync",
        description="SEC submissions metadata extraction and partition sync",
        module="edgar_sec.pipelines.metadata_sync.operator",
    ),
    LauncherEntry(
        id="filing-catalog",
        label="Filing Catalog",
        description="Offline DuckDB catalog materialization and target planning",
        module="edgar_sec.pipelines.filing_catalog.operator",
    ),
    LauncherEntry(
        id="inventory",
        label="Document Inventory",
        description="Discover fixtures and review SEC index pages",
        module="edgar_sec.pipelines.document_inventory.operator",
    ),
    LauncherEntry(
        id="planning",
        label="Document Planning",
        description="Resolve filing targets from published catalog and inventory evidence",
        module="edgar_sec.pipelines.document_planning.operator",
    ),
    LauncherEntry(
        id="acquisition",
        label="Document Acquisition",
        description="Project, acquire, and process selected document targets",
        module="edgar_sec.pipelines.document_acquisition.operator",
    ),
    LauncherEntry(
        id="documents",
        label="Document Storage",
        description="Document acquisition, normalization, snapshots, and review (removed soon)",
        module="edgar_sec.pipelines.document_storage.cli",
    ),
    LauncherEntry(
        id="viewer",
        label="Dataset Viewer",
        description="Read-only browser and SQL console over published artifacts",
        module="edgar_sec.apps.viewer.cli",
    ),
    LauncherEntry(
        id="dag",
        label="Snapshot DAG Console",
        description="Interactive DAG lineage, swimlane graphs, tags, branches, and maintenance",
        module="edgar_sec.infra.storage.dag.operator",
    ),
)


def _menu() -> int:
    print("\n==========================================")
    print("   EDGAR SEC Launcher (v2)                ")
    print("==========================================")
    while True:
        for idx, entry in enumerate(ENTRIES, start=1):
            print(f"  {idx}. {entry.label} - {entry.description}")
        print("  0. Exit")
        try:
            raw = input("\nChoice [0]: ").strip()
        except EOFError:
            return 0
        if not raw or raw == "0":
            return 0
        try:
            choice = int(raw)
            if 1 <= choice <= len(ENTRIES):
                entry = ENTRIES[choice - 1]
                import runpy

                runpy.run_module(entry.module, run_name="__main__", alter_sys=True)
                return 0
        except ValueError:
            pass
        print("Invalid choice, please select again.")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if not args:
        return _menu()
    if args[0] in ("-h", "--help"):
        print(__doc__)
        print("\nAvailable pipelines:")
        for entry in ENTRIES:
            print(f"  {entry.id:<15} {entry.description}")
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
