"""Inventory-owned transient path resolution for S4 broker-backed worker runs.

Wraps ``ProjectPaths.artifacts_root`` and the shared ``current_pointer_path`` /
``transient_dir`` helpers; adds no foundation path properties and never reuses
frozen ``DocumentStoragePaths``.
"""

from __future__ import annotations

import re
from pathlib import Path

from edgar_sec.foundation.runtime.paths import (
    current_pointer_path,
    transient_dir,
)

__all__ = [
    "ATTEMPT_PREFIX",
    "CHUNK_MANIFEST_FILE",
    "CHUNKS_DIR",
    "DATASET",
    "ENTRIES_FILE",
    "InventoryRunPaths",
    "LOCK_FILE",
    "OUTCOMES_FILE",
    "POINTER_FILE",
    "PUBLICATION_DIR",
    "RUN_MANIFEST_FILE",
    "SNAPSHOTS_DIR",
    "inventory_run_paths",
]

#: Dataset name under ``artifacts_root`` and ``transient/``.
DATASET = "document_inventory"

#: Files inside one attempt directory.
OUTCOMES_FILE = "outcomes.parquet"
ENTRIES_FILE = "entries.parquet"
CHUNK_MANIFEST_FILE = "manifest.json"

#: Files at the run root.
RUN_MANIFEST_FILE = "run_manifest.json"
LOCK_FILE = "run.lock"

#: Pointer naming the current committed attempt for a chunk.
POINTER_FILE = "current.json"

#: Directory names under a chunk.
CHUNKS_DIR = "chunks"

#: Prefix for one immutable attempt directory inside a chunk.
ATTEMPT_PREFIX = "attempt-"

#: S5-owned staging directory inside a run.
PUBLICATION_DIR = "publication"

#: Published snapshot root, owned by S5, separate from transient state.
SNAPSHOTS_DIR = "snapshots"

_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _validate_id(value: str, label: str) -> str:
    """Return ``value`` if it is a single safe path component, else raise."""
    if not isinstance(value, str) or not value or not _ID_RE.match(value):
        raise ValueError(f"invalid {label}: {value!r}")
    if value in (".", ".."):
        raise ValueError(f"invalid {label}: {value!r}")
    return value


class InventoryRunPaths:
    """Validated path methods for one inventory run.

    Every ID accepted here is validated as a single safe path component, so no
    method accepts an arbitrary relative path that could escape the run tree.
    """

    __slots__ = ("artifacts_root", "run_id", "run_root")

    def __init__(self, artifacts_root: Path, run_id: str) -> None:
        self.artifacts_root = Path(artifacts_root)
        self.run_id = _validate_id(run_id, "run_id")
        self.run_root = transient_dir(self.artifacts_root, DATASET, self.run_id)

    # --- run-level -------------------------------------------------------

    @property
    def snapshots_root(self) -> Path:
        """Published snapshot root, owned by S5."""
        return self.artifacts_root / DATASET / SNAPSHOTS_DIR

    def run_manifest_path(self) -> Path:
        return self.run_root / RUN_MANIFEST_FILE

    def lock_path(self) -> Path:
        return self.run_root / LOCK_FILE

    def publication_dir(self) -> Path:
        """S5-owned staging directory inside this run."""
        return self.run_root / PUBLICATION_DIR

    # --- chunk-level -----------------------------------------------------

    def chunk_dir(self, chunk_id: str) -> Path:
        return self.run_root / CHUNKS_DIR / _validate_id(chunk_id, "chunk_id")

    def chunk_pointer_path(self, chunk_id: str) -> Path:
        return self.chunk_dir(chunk_id) / POINTER_FILE

    def attempt_dir(self, chunk_id: str, attempt_id: str) -> Path:
        safe_attempt = _validate_id(attempt_id, "attempt_id")
        return self.chunk_dir(chunk_id) / f"{ATTEMPT_PREFIX}{safe_attempt}"

    def attempt_outcomes_path(self, chunk_id: str, attempt_id: str) -> Path:
        return self.attempt_dir(chunk_id, attempt_id) / OUTCOMES_FILE

    def attempt_entries_path(self, chunk_id: str, attempt_id: str) -> Path:
        return self.attempt_dir(chunk_id, attempt_id) / ENTRIES_FILE

    def attempt_manifest_path(self, chunk_id: str, attempt_id: str) -> Path:
        return self.attempt_dir(chunk_id, attempt_id) / CHUNK_MANIFEST_FILE

    # --- shared pointer --------------------------------------------------

    @staticmethod
    def current_pointer_path(snapshots_root: Path) -> Path:
        """Return the published-snapshot pointer for the inventory dataset."""
        return current_pointer_path(Path(snapshots_root))


def inventory_run_paths(artifacts_root: Path | str, run_id: str) -> InventoryRunPaths:
    """Construct validated inventory run paths from an artifacts root and run id."""
    return InventoryRunPaths(Path(artifacts_root), run_id)
