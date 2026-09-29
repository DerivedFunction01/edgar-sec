"""Root interactive launcher and CLI dispatcher for edgar_sec pipelines."""

from __future__ import annotations

import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class PipelineEntry:
    id: str
    label: str
    description: str
    module: str


ENTRIES: tuple[PipelineEntry, ...] = (
    PipelineEntry(
        id="metadata",
        label="Metadata Sync (Phase 01)",
        description="SEC submissions metadata extraction and partition sync",
        module="edgar_sec.pipelines.metadata_sync.operator",
    ),
    PipelineEntry(
        id="filing-catalog",
        label="Filing Catalog (Phase 02)",
        description="Offline DuckDB catalog materialization and target planning",
        module="edgar_sec.pipelines.filing_catalog.operator",
    ),
    PipelineEntry(
        id="documents",
        label="Document Storage (Phase 2.5)",
        description="Document acquisition, normalization, snapshots, and review",
        module="edgar_sec.pipelines.document_storage.cli",
    ),
)


def _menu() -> int:
    print("\n========================================")
    print("   EDGAR SEC Pipeline Launcher (v2)     ")
    print("========================================")
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
