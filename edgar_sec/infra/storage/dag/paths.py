"""Single owner for snapshot DAG filesystem layout and path resolution.

Consolidates directory structures and staging naming conventions so changes
propagate through one module instead of eight.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

CATALOG_DB_NAME = "catalog.sqlite"
BRANCHES_DIR_NAME = "branches"
TAGS_DIR_NAME = "tags"
STAGING_PREFIX = ".stage-"
PART_PREFIX = "part-"
PART_SUFFIX = ".parquet"
PUBLICATION_LOCK_FILE = ".publication.lock"


@dataclass(frozen=True, slots=True)
class DAGPaths:
    """Scoped filesystem layout for one snapshot DAG repository."""

    snapshots_root: Path

    @property
    def root(self) -> Path:
        return self.snapshots_root

    @property
    def catalog_file(self) -> Path:
        return self.root / CATALOG_DB_NAME

    @property
    def parts_root(self) -> Path:
        return self.root / "parts"

    # --- Branches ---

    @property
    def branches_root(self) -> Path:
        return self.root / BRANCHES_DIR_NAME

    def branch_dir(self, branch_name: str) -> Path:
        return self.branches_root / branch_name

    # --- Tags ---

    @property
    def tags_root(self) -> Path:
        return self.root / TAGS_DIR_NAME

    # --- Snapshot Nodes ---

    def snapshot_dir(self, snapshot_id: str) -> Path:
        return self.root / snapshot_id

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
    "CATALOG_DB_NAME",
    "DAGPaths",
    "PART_PREFIX",
    "PART_SUFFIX",
    "PUBLICATION_LOCK_FILE",
    "STAGING_PREFIX",
    "TAGS_DIR_NAME",
]
