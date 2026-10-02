"""Directory layout for the filing-catalog pipeline.

The layout composes from ``ProjectPaths.artifacts_root`` rather than from the
v1 ``manifests_root``/``transient_root`` accessors, which do not exist in v2.
The shape otherwise matches the v1 contract, because the artifact names and the
transient/published split are the interface Phase 2.5 consumes:

    artifacts_root/filing_catalog/<catalog_id>/              published, immutable
    artifacts_root/filing_catalog/current/pointer.json
    artifacts_root/filing_catalog/<feature_id>/              selection features, immutable
    artifacts_root/filing_catalog/<plan_id>/                  published, immutable
    artifacts_root/transient/filing_catalog/<catalog_id>/      staging, never published

Catalog snapshots and plan bundles are direct children of ``filing_catalog/``:
``snapshots_root`` and ``plans_root`` are the same directory, so a catalog id
and a plan id share one namespace. Both are 24-character content digests taken
from different inputs, so the only way to collide is a hash collision. The
feature snapshots named above share that same namespace and are content-addressed
by different rules, so they never collide either.

No ``.artifacts`` literal appears here; the root always arrives from
``resolve_paths()``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from edgar_sec.foundation.runtime.paths import (
    PLAN_FILE_NAME,
    POINTER_FILE_NAME,
    ProjectPaths,
    current_pointer_path,
    resolve_paths,
    transient_dir,
)

PIPELINE_DIR = "filing_catalog"

# Reference that resolves to whichever catalog the pointer names.
CURRENT_ALIAS = "current"

# Artifact names. Every module that reads or writes a published file names it
# through one of these constants; a literal repeated in two modules is how a
# rename desynchronizes a writer from its reader.
SNAPSHOT_FILE_NAME = "company_profiles.parquet"
SNAPSHOT_MANIFEST_NAME = "snapshot.manifest.json"
TARGETS_DIR_NAME = "filing_targets"
PLAN_TARGETS_DIR_NAME = "targets"
SELECTION_REPORT_NAME = "selection_report.json"
LOCATOR_GROUPS_NAME = "locator_groups.parquet"
EXPANSION_METADATA_NAME = "expansion_metadata.json"
# Reserve candidates: locator rows held back from the active set, so a
# downstream acquirer has replacements without a second selection run.
RESERVE_TARGETS_NAME = "reserve_targets.parquet"
# The normalized seed set a policy plan was selected against. Published with the
# plan so an expansion reproduces the parent's selection without re-reading a
# mutable external CSV.
SEED_FILERS_NAME = "seed_filers.csv"
# Selection policies live beside the plans they produce.
POLICIES_DIR_NAME = "policies"

REQUIRED_PLAN_FILES = (
    PLAN_FILE_NAME,
    SELECTION_REPORT_NAME,
    LOCATOR_GROUPS_NAME,
)

# Identifiers are interpolated into published directory names, so they are
# restricted to characters that need no escaping. Mirrors v1's ``_safe``.
_SAFE_ID_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
)


def safe_identifier(value: str) -> str:
    """Return ``value`` if it is safe to embed in a published path."""
    if not value or any(char not in _SAFE_ID_CHARS for char in value):
        raise ValueError(f"unsafe identifier: {value!r}")
    return value


def form_partition_name(form: str) -> str:
    """Escape a form name for use as a Hive-style partition directory name.

    Form names legitimately contain ``/`` (``8-K/A``, ``10-K/A``), which would
    otherwise be read as a directory separator and corrupt the partition layout.
    """
    return form.replace("/", "_")


def target_part_name(index: int) -> str:
    """Return the shard file name for one filing-targets part.

    Upstream shards may share a basename, so parts are numbered by resolved
    order rather than reusing the source name.
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
        """Root of published catalog snapshot directories."""
        return self.catalog_root

    @property
    def plans_root(self) -> Path:
        """Root of published target-plan bundles."""
        return self.catalog_root

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
        return self.snapshot_dir(catalog_id) / SNAPSHOT_MANIFEST_NAME

    @property
    def current_pointer(self) -> Path:
        """Atomic JSON pointer naming the currently published catalog."""
        return current_pointer_path(self.snapshots_root)

    def plan_dir(self, plan_id: str) -> Path:
        """Directory holding one immutable target-plan bundle."""
        return self.plans_root / safe_identifier(plan_id)

    def plan_targets_dir(self, plan_id: str) -> Path:
        """Directory holding the plan's per-form target partitions."""
        return self.plan_dir(plan_id) / PLAN_TARGETS_DIR_NAME

    def expansion_metadata(self, plan_id: str) -> Path:
        """Parent/child lineage record written by Stage B expansion."""
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
    "EXPANSION_METADATA_NAME",
    "LOCATOR_GROUPS_NAME",
    "PIPELINE_DIR",
    "PLAN_FILE_NAME",
    "PLAN_TARGETS_DIR_NAME",
    "POINTER_FILE_NAME",
    "POLICIES_DIR_NAME",
    "REQUIRED_PLAN_FILES",
    "RESERVE_TARGETS_NAME",
    "SEED_FILERS_NAME",
    "SELECTION_REPORT_NAME",
    "SNAPSHOT_FILE_NAME",
    "SNAPSHOT_MANIFEST_NAME",
    "TARGETS_DIR_NAME",
    "FilingCatalogPaths",
    "form_partition_dir",
    "form_partition_name",
    "resolve_filing_catalog_paths",
    "safe_identifier",
    "target_part_name",
]
