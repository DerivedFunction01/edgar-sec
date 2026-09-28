"""Directory layout for the metadata sync pipeline.

All paths derive from the shared artifacts root so the pipeline never embeds a
literal artifact directory. Plan-scoped transient checkpoints are separated
from published snapshots: chunks are resumability state, snapshots are output.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from edgar_sec.foundation.runtime.paths import (
    PLAN_FILE_NAME,
    ProjectPaths,
    current_pointer_path,
    resolve_paths,
    transient_dir,
)

METADATA_DIR = "metadata"
SNAPSHOT_FILE_NAME = "metadata.parquet"
SNAPSHOT_MANIFEST_NAME = "metadata.manifest.json"


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
        return self.metadata_root / "snapshots"

    def plan_dir(self, plan_id: str) -> Path:
        """Directory holding one immutable plan."""
        return self.metadata_root / "plans" / plan_id

    def transient_dir(self, plan_id: str) -> Path:
        """Directory holding one plan's transient chunk checkpoints."""
        return transient_dir(self.artifacts_root, METADATA_DIR, plan_id)

    def snapshot_dir(self, snapshot_id: str) -> Path:
        """Directory holding one published snapshot."""
        return self.snapshots_root / snapshot_id

    def snapshot_file(self, snapshot_id: str) -> Path:
        """Sorted Parquet dataset for one snapshot."""
        return self.snapshot_dir(snapshot_id) / SNAPSHOT_FILE_NAME

    def snapshot_manifest(self, snapshot_id: str) -> Path:
        """Merge manifest for one snapshot."""
        return self.snapshot_dir(snapshot_id) / SNAPSHOT_MANIFEST_NAME

    @property
    def current_pointer(self) -> Path:
        """Atomic JSON pointer naming the currently published snapshot."""
        return current_pointer_path(self.snapshots_root)

    def source_dir(self, source_name: str, snapshot_id: str) -> Path:
        """Directory holding one immutable external source snapshot."""
        return self.metadata_root / "sources" / source_name / snapshot_id

    def source_snapshot_file(self, source_name: str, snapshot_id: str) -> Path:
        """Raw payload of one immutable source snapshot."""
        return self.source_dir(source_name, snapshot_id) / "raw.json"

    def source_manifest_file(self, source_name: str, snapshot_id: str) -> Path:
        """Manifest describing one immutable source snapshot."""
        return self.source_dir(source_name, snapshot_id) / "manifest.json"


@dataclass(frozen=True, slots=True)
class RunPaths:
    """Plan-scoped paths for plan persistence and chunk checkpoints."""

    metadata: MetadataPaths
    plan_id: str

    @property
    def plan_file(self) -> Path:
        """Immutable plan document for this run."""
        return self.metadata.plan_dir(self.plan_id) / PLAN_FILE_NAME

    @property
    def chunk_dir(self) -> Path:
        """Transient chunk checkpoint directory for this run."""
        return self.metadata.transient_dir(self.plan_id)

    def chunk_file(self, chunk_id: int) -> Path:
        """Checkpoint path for one chunk."""
        return self.chunk_dir / f"chunk_{chunk_id:04d}.parquet"


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
    "METADATA_DIR",
    "MetadataPaths",
    "RunPaths",
    "resolve_metadata_paths",
    "resolve_run_paths",
]
