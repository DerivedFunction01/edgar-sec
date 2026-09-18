"""Typed domain path layout for Phase 2 filing extraction."""

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
class FilingExtractionPhasePaths:
    """Typed domain paths for Phase 2 (filing extraction)."""

    phase_paths: PhasePaths

    @property
    def project(self) -> ProjectPaths:
        return self.phase_paths.project

    @property
    def artifacts_root(self) -> Path:
        return self.project.artifacts_root

    @property
    def catalogs_root(self) -> Path:
        return self.project.transient_root / "filing_extraction" / "catalogs"

    @property
    def catalog_snapshots_dir(self) -> Path:
        return (
            self.project.manifests_root
            / "filing_extraction"
            / "filing_catalog"
            / "snapshots"
        )

    @property
    def manifests_filing_extraction_dir(self) -> Path:
        return self.project.manifests_root / "filing_extraction"

    @property
    def meta_submission_metadata_dir(self) -> Path:
        return self.project.manifests_root / "metadata" / "submission_metadata"

    @property
    def transient_root(self) -> Path:
        return self.project.transient_root

    @property
    def catalog_current_pointer_path(self) -> Path:
        return (
            self.project.manifests_root
            / "filing_extraction"
            / "filing_catalog"
            / "current.json"
        )

    def catalog_snapshot_dir(self, snapshot_id: str) -> Path:
        return self.catalog_snapshots_dir / _safe(snapshot_id)

    def catalog_snapshot_manifest_path(self, snapshot_id: str) -> Path:
        return self.catalog_snapshot_dir(snapshot_id) / "snapshot.manifest.json"

    def catalog_dir(self, catalog_id: str) -> Path:
        return self.catalogs_root / _safe(catalog_id)

    def company_profiles_path(self, catalog_id: str) -> Path:
        snap_dir = self.catalog_snapshot_dir(catalog_id)
        if snap_dir.exists():
            return snap_dir / "company_profiles.parquet"
        return self.catalog_dir(catalog_id) / "company_profiles.parquet"

    def filing_targets_dir(self, catalog_id: str) -> Path:
        snap_dir = self.catalog_snapshot_dir(catalog_id)
        if snap_dir.exists():
            return snap_dir / "filing_targets"
        return self.catalog_dir(catalog_id) / "filing_targets"


def resolve_filing_paths(
    run_id: str | None = None,
    env: dict | None = None,
) -> FilingExtractionPhasePaths:
    """Resolve typed Phase 2 domain paths."""
    resolved = resolve_paths("filing_extraction", run_id=run_id, env=env)
    if isinstance(resolved, PhasePaths):
        return FilingExtractionPhasePaths(resolved)
    return FilingExtractionPhasePaths(resolved.phase_paths)


__all__ = ["FilingExtractionPhasePaths", "resolve_filing_paths"]
