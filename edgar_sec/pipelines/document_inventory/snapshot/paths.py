"""Resolve immutable snapshot and transient publication paths."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from edgar_sec.foundation.runtime.paths import (
    current_pointer_path,
    transient_dir,
)
import edgar_sec.foundation.runtime.paths as foundation_paths

from edgar_sec.pipelines.document_inventory.paths import (
    DATASET,
    InventoryRunPaths,
)

__all__ = [
    "PART_SUFFIX",
    "SHARD_NAME",
    "SnapshotPaths",
    "snapshot_id_for",
    "snapshot_paths",
]

PART_SUFFIX = "part"
SHARD_NAME = "shard"
PART_PREFIX = "part-"
YEAR_PARTITION_NAME = "year"

_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def snapshot_id_for(parent_snapshot_id: str, digest: str) -> str:
    """Derive an immutable snapshot id from its parent and content digest.

    The digest combines parent id, changed page digests, new CIK edges, and
    schema/lookup versions; the snapshot id is opaque to callers.
    """
    content = f"{parent_snapshot_id}:{digest}"
    return f"snapshot-{hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]}"


def _validate_snapshot_id(value: str, label: str = "snapshot_id") -> str:
    if not isinstance(value, str) or not value or not _ID_RE.match(value):
        raise ValueError(f"invalid {label}: {value!r}")
    if value in (".", ".."):
        raise ValueError(f"invalid {label}: {value!r}")
    return value


class SnapshotPaths:
    """Validated paths for one snapshot or one publication staging tree."""

    __slots__ = (
        "artifacts_root",
        "dataset_root",
        "snapshot_id",
        "snapshot_dir",
        "_run",
    )

    def __init__(
        self,
        artifacts_root: Path | str,
        snapshot_id: str,
        *,
        base: InventoryRunPaths | None = None,
    ) -> None:
        self.artifacts_root = Path(artifacts_root).resolve()
        self.dataset_root = self.artifacts_root / DATASET
        self.snapshot_id = _validate_snapshot_id(snapshot_id, "snapshot_id")
        self.snapshot_dir = (
            self.dataset_root / foundation_paths.SNAPSHOTS_DIR / self.snapshot_id
        )
        self._run = base

    # --- published snapshot --------------------------------------------------

    @property
    def snapshots_root(self) -> Path:
        """Root under ``artifacts_root`` holding all snapshot directories."""
        return self.dataset_root / foundation_paths.SNAPSHOTS_DIR

    @property
    def current_pointer_path(self) -> Path:
        """The shared ``snapshots/current/pointer.json``."""
        return current_pointer_path(self.snapshots_root)

    def manifest_path(self) -> Path:
        return self.snapshot_dir / "manifest.json"

    def accessions_dir(self) -> Path:
        return self.snapshot_dir / "accessions"

    def accessions_part_path(self, year: str, part_index: int) -> Path:
        return (
            self.accessions_dir()
            / f"{YEAR_PARTITION_NAME}={year}"
            / f"{PART_PREFIX}{part_index}.{PART_SUFFIX}"
        )

    def entries_dir(self) -> Path:
        return self.snapshot_dir / "entries"

    def entries_part_path(self, year: str, part_index: int) -> Path:
        return (
            self.entries_dir()
            / f"{YEAR_PARTITION_NAME}={year}"
            / f"{PART_PREFIX}{part_index}.{PART_SUFFIX}"
        )

    def accession_sources_dir(self) -> Path:
        return self.snapshot_dir / "accession_sources"

    def accession_sources_part_path(self, year: str, part_index: int) -> Path:
        return (
            self.accession_sources_dir()
            / f"{YEAR_PARTITION_NAME}={year}"
            / f"{PART_PREFIX}{part_index}.{PART_SUFFIX}"
        )

    def lookups_dir(self) -> Path:
        return self.snapshot_dir / "lookups"

    def lookup_shard_path(self, lookup: str, shard_key: str) -> Path:
        return (
            self.lookups_dir()
            / lookup
            / f"{SHARD_NAME}={shard_key}"
            / f"{PART_PREFIX}0.{PART_SUFFIX}"
        )

    # --- transient publication staging ---------------------------------------

    @property
    def staging_root(self) -> Path:
        """Transient staging dir: {artifacts_root}/transient/{dataset}/{run_id}/publication/.

        Staged contents are validated, then moved wholesale to ``snapshot_dir``;
        a crash leaves only a staging tree with no visible effect.
        """
        if self._run is None:
            raise RuntimeError("staging requires the owning InventoryRunPaths")
        return self._run.publication_dir() / f".staging-{self.snapshot_id}"

    @property
    def staging_manifest_path(self) -> Path:
        return self.staging_root / "manifest.json"


def snapshot_paths(
    artifacts_root: Path | str,
    snapshot_id: str,
    *,
    base: InventoryRunPaths | None = None,
) -> SnapshotPaths:
    """Construct ``SnapshotPaths`` for a published snapshot id."""
    return SnapshotPaths(Path(artifacts_root), snapshot_id, base=base)
