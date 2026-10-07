"""Single owner for snapshot DAG filesystem layout and path resolution.

Consolidates directory structures, pointer locations, and staging naming
conventions so changes propagate through one module instead of eight.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from edgar_sec.foundation.runtime.paths import (
    POINTER_FILE_NAME,
    current_pointer_path,
)

MANIFEST_FILE_NAME = "manifest.json"
BRANCHES_DIR_NAME = "branches"
TAGS_DIR_NAME = "tags"
DEFAULT_REPOSITORY_DIR_NAME = "metadata"
STAGING_PREFIX = ".stage-"
PART_PREFIX = "part-"
PART_SUFFIX = ".parquet"
PUBLICATION_LOCK_FILE = ".publication.lock"
BRANCH_POINTER_GLOB = f"*/{POINTER_FILE_NAME}"
TAGS_JSON_GLOB = "*.json"


@dataclass(frozen=True, slots=True)
class DAGPaths:
    """Scoped filesystem layout for one snapshot DAG repository."""

    snapshots_root: Path

    @property
    def root(self) -> Path:
        return self.snapshots_root

    # --- Pointers & Branches ---

    @property
    def current_pointer(self) -> Path:
        return current_pointer_path(self.root)

    @property
    def branches_root(self) -> Path:
        return self.root / BRANCHES_DIR_NAME

    def branch_dir(self, branch_name: str) -> Path:
        return self.branches_root / branch_name

    def branch_pointer(self, branch_name: str) -> Path:
        return self.branch_dir(branch_name) / POINTER_FILE_NAME

    def pointer_for(self, branch_name: str | None = None) -> Path:
        if branch_name:
            return self.branch_pointer(branch_name)
        return self.current_pointer

    # --- Tags ---

    @property
    def tags_root(self) -> Path:
        return self.root / TAGS_DIR_NAME

    def tag_file(self, tag_name: str) -> Path:
        return self.tags_root / f"{tag_name}.json"

    # --- Snapshot Nodes & Manifests ---

    def snapshot_dir(self, snapshot_id: str) -> Path:
        return self.root / snapshot_id

    def manifest_file(self, snapshot_id: str) -> Path:
        return self.snapshot_dir(snapshot_id) / MANIFEST_FILE_NAME

    def relation_dir(self, snapshot_id: str, relation: str) -> Path:
        return self.snapshot_dir(snapshot_id) / relation

    def part_file(self, snapshot_id: str, relation: str, part_index: int) -> Path:
        return self.relation_dir(snapshot_id, relation) / (
            f"{PART_PREFIX}{part_index:05d}{PART_SUFFIX}"
        )

    # --- Staging & Work Directories ---

    def staging_dir(self, stage_id: str) -> Path:
        return self.root / f"{STAGING_PREFIX}{stage_id}"

    @property
    def publication_lock_path(self) -> Path:
        return self.root / PUBLICATION_LOCK_FILE

    @staticmethod
    def is_staging_name(name: str) -> bool:
        return name.startswith(STAGING_PREFIX)

    def staged_manifest_file(self, staged_dir: Path) -> Path:
        return staged_dir / MANIFEST_FILE_NAME

    def list_staging_dirs(self) -> list[Path]:
        if not self.root.is_dir():
            return []
        return [
            d
            for d in sorted(self.root.iterdir())
            if d.is_dir() and self.is_staging_name(d.name)
        ]


__all__ = [
    "BRANCHES_DIR_NAME",
    "BRANCH_POINTER_GLOB",
    "DAGPaths",
    "MANIFEST_FILE_NAME",
    "PART_PREFIX",
    "PART_SUFFIX",
    "PUBLICATION_LOCK_FILE",
    "STAGING_PREFIX",
    "TAGS_DIR_NAME",
    "TAGS_JSON_GLOB",
]
