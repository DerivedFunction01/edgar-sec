"""Directory layout for the metadata sync pipeline.

Transient checkpoints are kept apart from published snapshots, and a plan is a
directory, so a worker can be handed a copy and reassigned unchanged.
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
)

from .roster import ROSTER_FILE_NAME, SNAPSHOT_CIK_INDEX_NAME

METADATA_DIR = "metadata"
SNAPSHOT_FILE_NAME = "metadata.parquet"
SNAPSHOT_MANIFEST_NAME = "metadata.manifest.json"
PARTS_DIR_NAME = "parts"
ROSTER_DIR_NAME = "roster"
INPUT_DIR_NAME = "input"
INPUT_MANIFEST_NAME = "input_manifest.json"
ASSIGNMENTS_DIR_NAME = "assignments"
RECEIPT_FILE_NAME = "receipt.json"
RUN_LOCK_FILE = "run.lock"

REGISTRIES_DIR_NAME = "registries"

REGISTRY_EFFECTIVE_CIK_DATASET = "effective_ciks"
REGISTRY_EFFECTIVE_CIK_INPUT_NAME = "effective_cik_input.csv"
EFFECTIVE_CIK_INPUT_MANIFEST_NAME = "effective_cik_input.csv.manifest.json"

PLANS_DIR_NAME = "plans"
CHUNKS_DIR_NAME = "chunks"

FAMILY_INDEX_DIR_NAME = "family_index"
FAMILY_INDEX_FILE_NAME = "company_family.parquet"
FAMILY_INDEX_MANIFEST_NAME = "family_index.manifest.json"
FAMILY_INDEX_MANIFEST_KIND = "company_family_index"


@dataclass(frozen=True, slots=True)
class MetadataPaths:
    """Root-scoped metadata dataset layout, independent of any single run."""

    artifacts_root: Path

    @property
    def metadata_root(self) -> Path:
        """Root of the published metadata dataset."""
        return self.artifacts_root / METADATA_DIR

    @property
    def snapshots_root(self) -> Path:
        """Root of published snapshot directories."""
        return self.metadata_root / foundation_paths.SNAPSHOTS_DIR

    @property
    def plans_root(self) -> Path:
        """Root of published metadata plan bundles."""
        return self.metadata_root / PLANS_DIR_NAME

    def plan_dir(self, plan_id: str) -> Path:
        """Directory holding one immutable plan."""
        return self.plans_root / plan_id

    def transient_dir(self, plan_id: str) -> Path:
        """Directory holding one plan's transient chunk checkpoints."""
        return transient_dir(self.artifacts_root, METADATA_DIR, plan_id)

    def snapshot_dir(self, snapshot_id: str) -> Path:
        """Directory holding one published snapshot."""
        return self.snapshots_root / snapshot_id

    def snapshot_file(self, snapshot_id: str) -> Path:
        """Sorted Parquet dataset for one single-part snapshot.
        A multipart snapshot publishes ``parts/``; use ``read_snapshot_parts``.
        """
        return self.snapshot_dir(snapshot_id) / SNAPSHOT_FILE_NAME

    def snapshot_parts_dir(self, snapshot_id: str) -> Path:
        """Directory holding the Parquet parts of a multipart snapshot."""
        return self.snapshot_dir(snapshot_id) / PARTS_DIR_NAME

    def snapshot_part(self, snapshot_id: str, part_name: str) -> Path:
        """Path of one metadata part within a multipart snapshot."""
        return self.snapshot_parts_dir(snapshot_id) / part_name

    def snapshot_manifest(self, snapshot_id: str) -> Path:
        """Merge manifest for one snapshot."""
        return self.snapshot_dir(snapshot_id) / SNAPSHOT_MANIFEST_NAME

    def snapshot_cik_index(self, snapshot_id: str) -> Path:
        """Sorted distinct CIK index published beside one snapshot payload."""
        return self.snapshot_dir(snapshot_id) / SNAPSHOT_CIK_INDEX_NAME

    def registry_root(self, registry_id: str) -> Path:
        """Directory holding a content-addressed curated-input projection."""
        return self.metadata_root / REGISTRIES_DIR_NAME / registry_id

    def registry_manifest_root(self, registry_id: str) -> Path:
        """Directory holding one registry's published Parquet datasets."""
        return self.registry_root(registry_id) / "datasets"

    def registry_dataset(self, registry_id: str, dataset: str) -> Path:
        """Path of one published registry Parquet dataset."""
        return self.registry_manifest_root(registry_id) / f"{dataset}.parquet"

    def effective_input_file(self, registry_id: str) -> Path:
        """The effective CIK input CSV is an export for people; the roster Parquet
        dataset beside it is the carrier.
        """
        return self.registry_root(registry_id) / REGISTRY_EFFECTIVE_CIK_INPUT_NAME

    def effective_cik_roster(self, registry_id: str) -> Path:
        """Path of the effective CIK roster dataset for one registry."""
        return self.registry_dataset(registry_id, REGISTRY_EFFECTIVE_CIK_DATASET)

    @property
    def family_index_root(self) -> Path:
        """Root of published company-family assignments, one per content identity."""
        return self.metadata_root / FAMILY_INDEX_DIR_NAME

    def family_index_dir(self, family_index_id: str) -> Path:
        """Directory holding one immutable company-family assignment.

        The id is a content hash, so it needs no escaping, and it is not validated for
        the same reason `plan_dir` is not.
        """
        return self.family_index_root / family_index_id

    def family_index_file(self, family_index_id: str) -> Path:
        """Sorted assignment dataset of one row per CIK."""
        return self.family_index_dir(family_index_id) / FAMILY_INDEX_FILE_NAME

    def family_index_manifest(self, family_index_id: str) -> Path:
        """Manifest recording the roster and rules an assignment resolved from."""
        return self.family_index_dir(family_index_id) / FAMILY_INDEX_MANIFEST_NAME

    def snapshot_lock_path(self, snapshot_id: str) -> Path:
        """Exclusive run lock for a published snapshot (used by augment)."""
        return self.snapshot_dir(snapshot_id) / RUN_LOCK_FILE


@dataclass(frozen=True, slots=True)
class RunPaths:
    """Plan-scoped paths for the plan bundle and chunk checkpoints."""

    metadata: MetadataPaths
    plan_id: str

    @property
    def plan_file(self) -> Path:
        """Small execution manifest for this plan."""
        return self.metadata.plan_dir(self.plan_id) / PLAN_FILE_NAME

    @property
    def plan_bundle(self) -> Path:
        """Root of the immutable bundle copied to a worker."""
        return self.metadata.plan_dir(self.plan_id)

    @property
    def roster_file(self) -> Path:
        """The CIK cohort, stored once for the whole plan."""
        return self.plan_bundle / ROSTER_DIR_NAME / ROSTER_FILE_NAME

    @property
    def input_manifest_file(self) -> Path:
        """Diagnostics about where the selected cohort came from."""
        return self.plan_bundle / INPUT_DIR_NAME / INPUT_MANIFEST_NAME

    @property
    def assignments_dir(self) -> Path:
        """Directory holding one chunk-to-worker mapping per distribution."""
        return self.plan_bundle / ASSIGNMENTS_DIR_NAME

    def assignment_file(self, assignment_id: str) -> Path:
        """Path of one worker assignment dataset."""
        return self.assignments_dir / f"{assignment_id}.parquet"

    @property
    def chunk_dir(self) -> Path:
        """Transient chunk checkpoint directory for this run."""
        return self.metadata.transient_dir(self.plan_id)

    def chunk_file(self, chunk_id: int) -> Path:
        """Checkpoint path for one chunk."""
        return self.chunk_dir / f"chunk_{chunk_id:04d}.parquet"

    def lock_path(self) -> Path:
        """Exclusive run lock for this plan."""
        return self.metadata.plan_dir(self.plan_id) / RUN_LOCK_FILE


def resolve_metadata_paths(
    artifacts_root: str | Path | None = None, plan_id: str = ""
) -> MetadataPaths:
    """Resolve the metadata layout from an explicit root or the project defaults."""
    if artifacts_root is not None:
        return MetadataPaths(artifacts_root=Path(artifacts_root).resolve())
    return MetadataPaths(artifacts_root=resolve_paths().artifacts_root)


def resolve_run_paths(
    plan_id: str,
    artifacts_root: str | Path | None = None,
    project_paths: ProjectPaths | None = None,
) -> RunPaths:
    """Resolve plan-scoped paths for a given plan identifier."""
    if artifacts_root is not None:
        metadata = MetadataPaths(artifacts_root=Path(artifacts_root).resolve())
    elif project_paths is not None:
        metadata = MetadataPaths(artifacts_root=project_paths.artifacts_root)
    else:
        metadata = resolve_metadata_paths()
    return RunPaths(metadata=metadata, plan_id=plan_id)


__all__ = [
    "ASSIGNMENTS_DIR_NAME",
    "CHUNKS_DIR_NAME",
    "INPUT_DIR_NAME",
    "INPUT_MANIFEST_NAME",
    "METADATA_DIR",
    "PARTS_DIR_NAME",
    "PLANS_DIR_NAME",
    "RECEIPT_FILE_NAME",
    "REGISTRIES_DIR_NAME",
    "REGISTRY_EFFECTIVE_CIK_DATASET",
    "REGISTRY_EFFECTIVE_CIK_INPUT_NAME",
    "EFFECTIVE_CIK_INPUT_MANIFEST_NAME",
    "ROSTER_DIR_NAME",
    "RUN_LOCK_FILE",
    "SNAPSHOT_FILE_NAME",
    "SNAPSHOT_MANIFEST_NAME",
    "MetadataPaths",
    "RunPaths",
    "resolve_metadata_paths",
    "resolve_run_paths",
]
