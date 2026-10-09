"""Atomic snapshot publication with DAGCatalog ACID transactions.

Guarantees atomic pointer advancement and serializes concurrent writers.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.paths import PUBLICATION_LOCK_FILE
from .manifest import DAGNodeManifest


class PublicationLockError(RuntimeError):
    """A non-blocking publication lock request found another writer."""


class StaleParentError(RuntimeError):
    """The expected parent snapshot ID differs from the current pointer."""


class PublicationLock:
    """Exclusive filesystem lock serializing snapshot publications."""

    def __init__(self, lock_path: Any, *, blocking: bool = True) -> None:
        import fcntl
        import os

        raw = getattr(lock_path, "publication_lock_path", lock_path)
        resolved = Path(raw)
        self.path = (
            resolved / PUBLICATION_LOCK_FILE
            if isinstance(raw, (Path, str)) and resolved.is_dir()
            else resolved
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        operation = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(self._descriptor, operation)
        except BlockingIOError as exc:
            os.close(self._descriptor)
            self._descriptor = -1
            raise PublicationLockError(
                f"publication lock is held: {self.path}"
            ) from exc

    def close(self) -> None:
        import fcntl
        import os

        if getattr(self, "_descriptor", -1) >= 0:
            fcntl.flock(self._descriptor, fcntl.LOCK_UN)
            os.close(self._descriptor)
            self._descriptor = -1

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()


def read_pointer_id(pointer_file: Path | str) -> str | None:
    """Return the snapshot_id from a catalog, or None if absent."""
    path = Path(pointer_file)
    if not path.exists():
        return None
    if path.name == "catalog.sqlite" or path.is_dir():
        root = path.parent if path.is_file() else path
        ptr = DAGCatalog(root).read_pointer()
        return str(ptr["snapshot_id"]) if ptr else None
    return None


def publish_node(
    snapshots_root: Path | str,
    manifest: DAGNodeManifest,
    staged_dir: Path | str | None = None,
    expected_parent_id: str | None = None,
    *,
    branch_name: str | None = None,
    blocking_lock: bool = True,
) -> Path:
    """Atomically record a node in DAGCatalog and advance the branch pointer.
    The compare-and-move runs under one exclusive lock; a stale tip leaves the
    pointer unchanged. expected_parent_id guards the tip, distinct from parents."""
    root = Path(snapshots_root)
    catalog = DAGCatalog(root)
    target_branch = branch_name or "main"

    with PublicationLock(catalog.catalog_file, blocking=blocking_lock):
        current = catalog.read_pointer(target_branch)
        current_id = current["snapshot_id"] if current else None
        if current_id != expected_parent_id:
            raise StaleParentError(
                f"expected parent {expected_parent_id!r}, current is {current_id!r}"
            )
        target_dir = root / manifest.snapshot_id
        if staged_dir is not None:
            staged = Path(staged_dir)
            if staged.exists() and not target_dir.exists():
                shutil.move(str(staged), str(target_dir))

        catalog.publish_node(manifest, branch_name=target_branch)
    return target_dir


def read_pointer(
    snapshots_root: Path | str, branch_name: str | None = None
) -> dict[str, Any] | None:
    """Return dictionary payload of branch pointer, or None if missing."""
    catalog = DAGCatalog(snapshots_root)
    target_branch = branch_name or "main"
    ptr = catalog.read_pointer(target_branch)
    if ptr is None:
        return None
    return {
        "snapshot_id": ptr["snapshot_id"],
        "branch_name": target_branch,
        "updated_at": ptr["updated_at"],
    }


def checkout_tip(
    snapshots_root: Path | str,
    target_snapshot_id: str,
    *,
    branch_name: str | None = None,
) -> Path:
    """Atomically swing branch pointer to a target snapshot."""
    catalog = DAGCatalog(snapshots_root)
    if not catalog.has_snapshot(target_snapshot_id):
        raise FileNotFoundError(
            f"target snapshot missing from catalog: {target_snapshot_id}"
        )
    target_branch = branch_name or "main"
    catalog.write_pointer(target_branch, target_snapshot_id)
    return catalog.catalog_file


def list_branches(snapshots_root: Path | str) -> list[str]:
    """Return all branch names in the catalog."""
    catalog = DAGCatalog(snapshots_root)
    return sorted(catalog.list_branches().keys())


def create_branch(
    snapshots_root: Path | str,
    branch_name: str,
    snapshot_id: str,
) -> Path:
    """Create or advance a named branch pointer to a snapshot."""
    if branch_name in ("current", ""):
        raise ValueError("branch name cannot be 'current' or empty")
    return checkout_tip(snapshots_root, snapshot_id, branch_name=branch_name)


def delete_branch(snapshots_root: Path | str, branch_name: str) -> bool:
    """Delete a named branch pointer."""
    if branch_name in ("current", "main", ""):
        raise ValueError(f"cannot delete protected branch {branch_name!r}")
    catalog = DAGCatalog(snapshots_root)
    with catalog._connect() as con:
        cur = con.execute("DELETE FROM branches WHERE name = ?", (branch_name,))
        return cur.rowcount > 0


__all__ = [
    "PublicationLock",
    "PublicationLockError",
    "StaleParentError",
    "checkout_tip",
    "create_branch",
    "delete_branch",
    "list_branches",
    "publish_node",
    "read_pointer",
    "read_pointer_id",
]
