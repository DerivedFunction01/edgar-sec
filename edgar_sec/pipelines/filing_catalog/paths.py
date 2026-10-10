"""Directory layout for the filing-catalog pipeline.
The ``current`` pointer lives inside ``snapshots/``; the DAG catalog identifies
published catalog snapshots separately from policy feature snapshots.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import edgar_sec.foundation.runtime.paths as foundation_paths
from edgar_sec.foundation.runtime.paths import (
    PLAN_FILE_NAME,
    ProjectPaths,
    resolve_paths,
    transient_dir,
    validate_safe_id,
)
from edgar_sec.infra.storage.dag.paths import DAGPaths
from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths

PIPELINE_DIR = "filing_catalog"

# Published subdirectories.
PLANS_DIR = foundation_paths.PLANS_DIR

# Reference that resolves to whichever catalog the pointer names.
CURRENT_ALIAS = "current"

# Artifact names, named through constants because a literal repeated in two
# modules is how a rename desynchronizes a writer from its reader.
SNAPSHOT_FILE = "company_profiles.parquet"
TARGETS_DIR = "filing_targets"
PLAN_TARGETS_DIR = "targets"
SELECTION_REPORT_FILE = "selection_report.json"
LOCATOR_GROUPS_FILE = "locator_groups.parquet"
EXPANSION_METADATA_FILE = "expansion_metadata.json"
# Reserve candidates: locator rows held back from the active set, so a
# downstream acquirer has replacements without a second selection run.
RESERVE_TARGETS_FILE = "reserve_targets.parquet"
# Published with the plan so an expansion reproduces the parent's selection
# without re-reading a mutable external CSV.
SEED_FILERS_FILE = "seed_filers.csv"
# Selection policies live beside the plans they produce.
POLICIES_DIR = "policies"

REQUIRED_PLAN_FILES = (
    PLAN_FILE_NAME,
    SELECTION_REPORT_FILE,
    LOCATOR_GROUPS_FILE,
)


def form_partition_name(form: str) -> str:
    """Escape a form name for a Hive-style partition directory name.

    Form names contain ``/`` (``8-K/A``), read as a directory separator otherwise.
    """
    return form.replace("/", "_")


def target_part_name(index: int) -> str:
    """Return the shard file name for one filing-targets part.

    Numbered by resolved order, not by reusing a source basename shards may share.
    """
    return f"part-{index:05d}.parquet"


@dataclass(frozen=True, slots=True)
class FilingCatalogPaths:
    """Root-scoped catalog layout, independent of any single run."""

    artifacts_root: Path

    @property
    def catalog_root(self) -> Path:
        """Root of the published catalog dataset."""
        return self.artifacts_root / PIPELINE_DIR

    @property
    def snapshots_root(self) -> Path:
        """Root of published catalog snapshot directories, and of the pointer."""
        return self.catalog_root / foundation_paths.SNAPSHOTS_DIR

    @property
    def plans_root(self) -> Path:
        """Root of published target-plan bundles."""
        return self.catalog_root / PLANS_DIR

    @property
    def policies_root(self) -> Path:
        """Root of published selection policies."""
        return self.catalog_root / POLICIES_DIR

    def snapshot_dir(self, catalog_id: str) -> Path:
        """Directory holding one immutable catalog snapshot."""
        return self.snapshots_root / validate_safe_id(catalog_id)

    def snapshot_profiles_file(self, catalog_id: str) -> Path:
        """Deduplicated registrant profile dataset for one snapshot."""
        return self.snapshot_dir(catalog_id) / SNAPSHOT_FILE

    def snapshot_targets_dir(self, catalog_id: str) -> Path:
        """Directory holding the sharded filing-target dataset."""
        return self.snapshot_dir(catalog_id) / TARGETS_DIR

    @property
    def catalog_file(self) -> Path:
        """SQLite DAG catalog database for published catalog snapshots."""
        return DAGPaths(self.snapshots_root).catalog_file

    def plan_dir(self, plan_id: str) -> Path:
        """Directory holding one immutable target-plan bundle."""
        return self.plans_root / validate_safe_id(plan_id)

    def plan_seed_filers(self, plan_id: str) -> Path:
        """The plan's normalized seed sidecar, published with a policy plan."""
        return self.plan_dir(plan_id) / SEED_FILERS_FILE

    def transient_catalog_dir(self, catalog_id: str) -> Path:
        """Staging directory for one catalog, never published."""
        return transient_dir(
            self.artifacts_root, PIPELINE_DIR, validate_safe_id(catalog_id)
        )


def resolve_filing_catalog_paths(
    artifacts_root: str | Path | None = None,
    project_paths: ProjectPaths | None = None,
) -> FilingCatalogPaths:
    """Resolve the catalog layout from an explicit root or the project default."""
    if artifacts_root is not None:
        return FilingCatalogPaths(artifacts_root=Path(artifacts_root).resolve())
    if project_paths is not None:
        return FilingCatalogPaths(artifacts_root=project_paths.artifacts_root)
    return FilingCatalogPaths(artifacts_root=resolve_paths().artifacts_root)


__all__ = [
    "CURRENT_ALIAS",
    "EXPANSION_METADATA_FILE",
    "LOCATOR_GROUPS_FILE",
    "PIPELINE_DIR",
    "PLANS_DIR",
    "PLAN_TARGETS_DIR",
    "POLICIES_DIR",
    "REQUIRED_PLAN_FILES",
    "RESERVE_TARGETS_FILE",
    "SEED_FILERS_FILE",
    "SELECTION_REPORT_FILE",
    "SNAPSHOT_FILE",
    "TARGETS_DIR",
    "FilingCatalogPaths",
    "form_partition_name",
    "resolve_filing_catalog_paths",
    "validate_safe_id",
    "target_part_name",
]
