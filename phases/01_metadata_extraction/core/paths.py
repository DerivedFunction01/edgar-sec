"""Typed domain path layout for Phase 1 metadata extraction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from defs.runtime.paths import PhasePaths, ProjectPaths, resolve_paths

_SAFE_ID_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
)


def _safe(value: str) -> str:
    if not value or any(c not in _SAFE_ID_CHARS for c in value):
        raise ValueError(f"unsafe identifier: {value!r}")
    return value


@dataclass(frozen=True)
class MetadataPhasePaths:
    """Typed domain paths for Phase 1 (metadata extraction)."""

    phase_paths: PhasePaths

    @property
    def project(self) -> ProjectPaths:
        return self.phase_paths.project

    @property
    def artifacts_root(self) -> Path:
        return self.project.artifacts_root

    # Raw observation sources
    @property
    def sources_root(self) -> Path:
        return self.artifacts_root / "metadata" / "sources"

    def source_snapshots_dir(self, source: str) -> Path:
        return self.sources_root / _safe(source) / "snapshots"

    def source_snapshot_path(
        self, source: str, snapshot_id: str, suffix: str = ".json"
    ) -> Path:
        return self.source_snapshots_dir(source) / f"{_safe(snapshot_id)}{suffix}"

    def source_manifest_dir(self, source: str) -> Path:
        return self.source_snapshots_dir(source)

    def source_manifest_path(self, source: str, snapshot_id: str) -> Path:
        return self.source_snapshots_dir(source) / f"{_safe(snapshot_id)}.manifest.json"

    # Registries
    @property
    def registries_root(self) -> Path:
        return self.artifacts_root / "metadata" / "registries" / "snapshots"

    def registry_snapshot_root(self, registry_id: str) -> Path:
        return self.registries_root / _safe(registry_id)

    def registry_snapshot_path(self, registry_id: str, name: str) -> Path:
        return self.registry_snapshot_root(registry_id) / name

    def registry_manifest_root(self, registry_id: str) -> Path:
        return self.registry_snapshot_root(registry_id)

    def registry_manifest_path(self, registry_id: str, name: str) -> Path:
        return self.registry_manifest_root(registry_id) / name

    # Worklists
    def worklist_root(self, run_id: str) -> Path:
        return self.artifacts_root / "metadata" / "worklists" / _safe(run_id)

    def worklist_path(self, run_id: str) -> Path:
        return self.worklist_root(run_id) / "worklist.parquet"

    # Submission metadata snapshots
    @property
    def snapshots_dir(self) -> Path:
        return self.project.dataset_snapshots_dir("metadata", "submission_metadata")

    def snapshot_dir(self, snapshot_id: str) -> Path:
        return self.project.dataset_snapshot_dir(
            "metadata", "submission_metadata", snapshot_id
        )

    def snapshot_manifest_path(self, snapshot_id: str) -> Path:
        return self.project.dataset_snapshot_manifest_path(
            "metadata", "submission_metadata", snapshot_id
        )

    def snapshot_parts_dir(self, snapshot_id: str, shard_id: str | None = None) -> Path:
        return self.project.dataset_snapshot_parts_dir(
            "metadata", "submission_metadata", snapshot_id, shard_id
        )

    def snapshot_replacement_keys_dir(self, snapshot_id: str) -> Path:
        return self.project.dataset_snapshot_replacement_keys_dir(
            "metadata", "submission_metadata", snapshot_id
        )

    @property
    def current_snapshot_pointer_path(self) -> Path:
        return self.project.dataset_current_pointer_path(
            "metadata", "submission_metadata"
        )

    def run_paths(self, run_id: str):
        return self.phase_paths.run(_safe(run_id))

    def augmentation_partition_dataset_path(
        self,
        run_id: str,
        partition_id: int | str,
        storage_format: str = "parquet",
    ) -> Path:
        return self.project.published_augmentation_partition_dataset_path(
            "metadata",
            "submission_metadata",
            _safe(run_id),
            partition_id,
            storage_format,
        )



def resolve_metadata_paths(
    run_id: str | None = None,
    env: dict | None = None,
) -> MetadataPhasePaths:
    """Resolve typed Phase 1 domain paths."""
    resolved = resolve_paths("metadata", run_id=run_id, env=env)
    if isinstance(resolved, PhasePaths):
        return MetadataPhasePaths(resolved)
    return MetadataPhasePaths(resolved.phase_paths)


__all__ = ["MetadataPhasePaths", "resolve_metadata_paths"]
