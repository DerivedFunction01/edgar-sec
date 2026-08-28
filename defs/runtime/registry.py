"""Static launcher registry for the root ``run.py`` dispatcher.

Pure declarative data: each entry names the module that owns its own
argparse/interactive behavior; the launcher adds no phase logic. Adding a
phase or tool later means adding one ``LauncherEntry`` here — the contract
test pins that every registered module imports and exposes ``main``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LauncherEntry:
    """One dispatchable entry point of the repository launcher."""

    id: str
    label: str
    description: str
    module: str


ENTRIES: tuple[LauncherEntry, ...] = (
    LauncherEntry(
        id="viewer",
        label="Dataset Viewer",
        description="read-only artifact viewer (API + UI)",
        module="defs.viewer.__main__",
    ),
    LauncherEntry(
        id="metadata",
        label="Phase 01: Metadata Extraction",
        description="interactive SEC 10-K metadata extraction wizard",
        module="phases.01_metadata_extraction.run",
    ),
    LauncherEntry(
        id="filing-catalog",
        label="Phase 02: Filing Catalog",
        description="no-network filing catalog and target planner",
        module="phases.02_filing_extraction.run",
    ),
    LauncherEntry(
        id="artifact-bundle",
        label="Artifact Bundle",
        description="portable finalized artifact transport",
        module="defs.runtime.bundle",
    ),
    LauncherEntry(
        id="settings",
        label="Settings & .env",
        description="generate a documented .env template from the settings registry",
        module="defs.runtime.settings_cli",
    ),
)


def find_entry(entry_id: str) -> LauncherEntry | None:
    """Return the entry with the given id, or ``None`` when unknown."""
    for entry in ENTRIES:
        if entry.id == entry_id:
            return entry
    return None


__all__ = ["ENTRIES", "LauncherEntry", "find_entry"]
