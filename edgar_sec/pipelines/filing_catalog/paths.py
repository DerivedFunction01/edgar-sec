"""Directory layout for the filing-catalog pipeline.
The ``current`` pointer lives *inside* ``snapshots/``, whose siblings are exactly
the snapshot directories it can name. That directory also holds policy-scope
feature snapshots, told apart by manifest. Staging stays transient, never published.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import edgar_sec.foundation.runtime.paths as foundation_paths
from edgar_sec.foundation.runtime.paths import (
    ProjectPaths,
    resolve_paths,
    transient_dir,
)
from edgar_sec.infra.storage.dag.paths import DAGPaths
from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths

PIPELINE_DIR = "filing_catalog"

# Published subdirectories.
PLANS_DIR_NAME = "plans"

# Reference that resolves to whichever catalog the pointer names.
CURRENT_ALIAS = "current"

# Artifact names, named through constants because a literal repeated in two
# modules is how a rename desynchronizes a writer from its reader.
SNAPSHOT_FILE_NAME = "company_profiles.parquet"
CATALOG_SNAPSHOT_MANIFEST_NAME = "snapshot.manifest.json"
TARGETS_DIR_NAME = "filing_targets"
PLAN_TARGETS_DIR_NAME = "targets"
SELECTION_REPORT_NAME = "selection_report.json"
LOCATOR_GROUPS_NAME = "locator_groups.parquet"
EXPANSION_METADATA_NAME = "expansion_metadata.json"
# Reserve candidates: locator rows held back from the active set, so a
# downstream acquirer has replacements without a second selection run.
RESERVE_TARGETS_NAME = "reserve_targets.parquet"
# Published with the plan so an expansion reproduces the parent's selection
# without re-reading a mutable external CSV.
SEED_FILERS_NAME = "seed_filers.csv"
# Selection policies live beside the plans they produce.
POLICIES_DIR_NAME = "policies"

REQUIRED_PLAN_FILES = (
    foundation_paths.PLAN_FILE_NAME,
    SELECTION_REPORT_NAME,
    LOCATOR_GROUPS_NAME,
)

# Identifiers are interpolated into published directory names, so they are
# restricted to characters that need no escaping.
_SAFE_ID_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
)


def safe_identifier(value: str) -> str:
    """Return ``value`` if it is safe to embed in a published path."""
    if not value or any(char not in _SAFE_ID_CHARS for char in value):
        raise ValueError(f"unsafe identifier: {value!r}")
    return value


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


def form_partition_dir(plan_dir: Path, form: str) -> Path:
    """Return the partition directory holding one form's rows in a plan."""
    return plan_dir / PLAN_TARGETS_DIR_NAME / f"form={form_partition_name(form)}"


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
        return self.catalog_root / PLANS_DIR_NAME

    @property
    def policies_root(self) -> Path:
        """Root of published selection policies."""
        return self.catalog_root / POLICIES_DIR_NAME

    def snapshot_dir(self, catalog_id: str) -> Path:
        """Directory holding one immutable catalog snapshot."""
        return self.snapshots_root / safe_identifier(catalog_id)

    def snapshot_profiles_file(self, catalog_id: str) -> Path:
        """Deduplicated registrant profile dataset for one snapshot."""
        return self.snapshot_dir(catalog_id) / SNAPSHOT_FILE_NAME

    def snapshot_targets_dir(self, catalog_id: str) -> Path:
        """Directory holding the sharded filing-target dataset."""
        return self.snapshot_dir(catalog_id) / TARGETS_DIR_NAME

    def snapshot_manifest(self, catalog_id: str) -> Path:
        """Materialization manifest for one snapshot."""
        return self.snapshot_dir(catalog_id) / CATALOG_SNAPSHOT_MANIFEST_NAME

    @property
    def catalog_file(self) -> Path:
        """SQLite DAG catalog database for published catalog snapshots."""
        return DAGPaths(self.snapshots_root).catalog_file

    def plan_dir(self, plan_id: str) -> Path:
        """Directory holding one immutable target-plan bundle."""
        return self.plans_root / safe_identifier(plan_id)

    def plan_targets_dir(self, plan_id: str) -> Path:
        """Directory holding the plan's per-form target partitions."""
        return self.plan_dir(plan_id) / PLAN_TARGETS_DIR_NAME

    def expansion_metadata(self, plan_id: str) -> Path:
        """Parent/child lineage record written by policy-scope expansion."""
        return self.plan_dir(plan_id) / EXPANSION_METADATA_NAME

    def plan_seed_filers(self, plan_id: str) -> Path:
        """The plan's normalized seed sidecar, published with a policy plan."""
        return self.plan_dir(plan_id) / SEED_FILERS_NAME

    def transient_catalog_dir(self, catalog_id: str) -> Path:
        """Staging directory for one catalog, never published."""
        return transient_dir(
            self.artifacts_root, PIPELINE_DIR, safe_identifier(catalog_id)
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
    "CATALOG_SNAPSHOT_MANIFEST_NAME",
    "EXPANSION_METADATA_NAME",
    "LOCATOR_GROUPS_NAME",
    "PIPELINE_DIR",
    "PLANS_DIR_NAME",
    "PLAN_TARGETS_DIR_NAME",
    "POLICIES_DIR_NAME",
    "REQUIRED_PLAN_FILES",
    "RESERVE_TARGETS_NAME",
    "SEED_FILERS_NAME",
    "SELECTION_REPORT_NAME",
    "SNAPSHOT_FILE_NAME",
    "TARGETS_DIR_NAME",
    "FilingCatalogPaths",
    "form_partition_dir",
    "form_partition_name",
    "resolve_filing_catalog_paths",
    "resolve_metadata_paths",
    "safe_identifier",
    "target_part_name",
]
