"""Static launcher registry for the root ``run.py`` dispatcher.

Pure declarative data: each entry names the module that owns its own
argparse/interactive behavior; the launcher adds no phase logic. Adding a
phase or tool later means adding one ``LauncherEntry`` here — the contract
test pins that every registered module imports and exposes ``main``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PhaseDependency:
    """One upstream dataset requirement for a pipeline phase."""

    phase: str
    dataset: str
    description: str = ""
    required: bool = True


@dataclass(frozen=True)
class LauncherEntry:
    """One dispatchable entry point of the repository launcher."""

    id: str
    label: str
    description: str
    module: str
    dependencies: tuple[PhaseDependency, ...] = ()


ENTRIES: tuple[LauncherEntry, ...] = (
    LauncherEntry(
        id="table-probe",
        label="Table Taxonomy & Vocabulary Probe",
        description="pipeline table census, firm vocabulary explorer, and classifier benchmark",
        module="defs.taxonomy.probe.cli",
    ),
    LauncherEntry(
        id="viewer",
        label="Dataset Viewer",
        description="read-only artifact viewer (API + UI)",
        module="defs.viewer.__main__",
    ),
    LauncherEntry(
        id="metadata",
        label="Phase 01: Metadata Extraction",
        description="interactive SEC metadata extraction wizard",
        module="phases.01_metadata_extraction.run",
    ),
    LauncherEntry(
        id="filing-catalog",
        label="Phase 02: Filing Catalog",
        description="no-network filing catalog and target planner",
        module="phases.02_filing_extraction.run",
        dependencies=(
            PhaseDependency(
                phase="metadata",
                dataset="submission_metadata",
                description="Phase 01 verified submission metadata",
            ),
        ),
    ),
    LauncherEntry(
        id="webpage-storage",
        label="Phase 2.5: Webpage Storage",
        description="raw SEC filing document acquisition and storage",
        module="phases.025_webpage_storage.run",
        dependencies=(
            PhaseDependency(
                phase="filing-catalog",
                dataset="filing_targets",
                description="Phase 02 finalized target plan",
            ),
        ),
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


def get_phase_dependencies(phase_or_entry_id: str) -> tuple[PhaseDependency, ...]:
    """Return declared upstream dependencies for a phase or launcher entry."""
    entry = find_entry(phase_or_entry_id)
    if entry is not None:
        return entry.dependencies
    for item in ENTRIES:
        if (
            item.module.startswith(f"phases.{phase_or_entry_id}")
            or item.id == phase_or_entry_id
        ):
            return item.dependencies
    return ()


__all__ = [
    "ENTRIES",
    "LauncherEntry",
    "PhaseDependency",
    "find_entry",
    "get_phase_dependencies",
]
