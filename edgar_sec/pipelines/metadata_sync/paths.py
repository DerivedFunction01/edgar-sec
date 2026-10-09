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
    RUN_LOCK_FILE,
    transient_dir,
)

from .roster import ROSTER_FILE_NAME, SNAPSHOT_CIK_INDEX_NAME

METADATA_DIR = "metadata"
PARTS_DIR = "parts"
ROSTER_DIR = "roster"
INPUT_DIR = "input"
INPUT_MANIFEST_FILE = "input_manifest.json"
ASSIGNMENTS_DIR = "assignments"
RECEIPT_FILE = "receipt.json"

PLANS_DIR = foundation_paths.PLANS_DIR
CHUNKS_DIR = foundation_paths.CHUNKS_DIR


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
        return self.metadata_root / PLANS_DIR

    def plan_dir(self, plan_id: str) -> Path:
        """Directory holding one immutable plan."""
        return self.plans_root / plan_id

    def transient_dir(self, plan_id: str) -> Path:
        """Directory holding one plan's transient chunk checkpoints."""
        return transient_dir(self.artifacts_root, METADATA_DIR, plan_id)

    def snapshot_dir(self, snapshot_id: str) -> Path:
        """Directory holding one published snapshot."""
        return self.snapshots_root / snapshot_id

    def snapshot_parts_dir(self, snapshot_id: str) -> Path:
        """Directory holding the Parquet parts of a multipart snapshot."""
        return self.snapshot_dir(snapshot_id) / PARTS_DIR

    def snapshot_part(self, snapshot_id: str, part_name: str) -> Path:
        """Path of one metadata part within a multipart snapshot."""
        return self.snapshot_parts_dir(snapshot_id) / part_name

    def snapshot_cik_index(self, snapshot_id: str) -> Path:
        """Sorted distinct CIK index published beside one snapshot payload."""
        return self.snapshot_dir(snapshot_id) / SNAPSHOT_CIK_INDEX_NAME

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
        return self.plan_bundle / ROSTER_DIR / ROSTER_FILE_NAME

    @property
    def input_manifest_file(self) -> Path:
        """Diagnostics about where the selected cohort came from."""
        return self.plan_bundle / INPUT_DIR / INPUT_MANIFEST_FILE

    @property
    def assignments_dir(self) -> Path:
        """Directory holding one chunk-to-worker mapping per distribution."""
        return self.plan_bundle / ASSIGNMENTS_DIR

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
    "ASSIGNMENTS_DIR",
    "CHUNKS_DIR",
    "INPUT_DIR",
    "INPUT_MANIFEST_FILE",
    "METADATA_DIR",
    "PARTS_DIR",
    "PLANS_DIR",
    "RECEIPT_FILE",
    "ROSTER_DIR",
    "RUN_LOCK_FILE",
    "MetadataPaths",
    "RunPaths",
    "resolve_metadata_paths",
    "resolve_run_paths",
]
