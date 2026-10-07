"""Atomic snapshot publication with file locks and CAS pointer updates.

Guarantees atomic pointer advancement and serializes concurrent writers.
"""

from __future__ import annotations

import fcntl
import json
import os
import shutil
from pathlib import Path
from types import TracebackType
from typing import Any, Self

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.runtime.paths import current_pointer_path
from edgar_sec.infra.storage.atomic import _fsync_dir, atomic_write_json

from .manifest import DAGNodeManifest


class PublicationLockError(RuntimeError):
    """A non-blocking publication lock request found another writer."""


class StaleParentError(RuntimeError):
    """The expected parent snapshot ID differs from the current pointer."""


class PublicationLock:
    """Exclusive filesystem lock serializing snapshot publications."""

    def __init__(self, lock_path: Any, *, blocking: bool = True) -> None:
        self.path = Path(getattr(lock_path, "publication_lock_path", lock_path))
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
        _fsync_dir(str(self.path.parent))

    def close(self) -> None:
        if self._descriptor >= 0:
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
    """Return the snapshot_id from a pointer file, or None if absent."""
    path = Path(pointer_file)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return str(data.get("snapshot_id")) if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def pointer_path_for(snapshots_root: Path, branch_name: str | None = None) -> Path:
    """Resolve the pointer file path for current or a named branch."""
    if branch_name:
        return snapshots_root / "branches" / branch_name / "pointer.json"
    return current_pointer_path(snapshots_root)


def publish_node(
    snapshots_root: Path | str,
    manifest: DAGNodeManifest,
    staged_dir: Path | str,
    expected_parent_id: str | None,
    *,
    branch_name: str | None = None,
    blocking_lock: bool = True,
) -> Path:
    """Install staged snapshot directory and atomically advance pointer."""
    root = Path(snapshots_root)
    staged = Path(staged_dir)
    target_dir = root / manifest.snapshot_id
    lock_file = root / ".publication.lock"
    pointer_file = pointer_path_for(root, branch_name)

    with PublicationLock(lock_file, blocking=blocking_lock):
        current_id = read_pointer_id(pointer_file)
        if current_id != expected_parent_id:
            raise StaleParentError(
                f"expected parent {expected_parent_id!r}, current is {current_id!r}"
            )

        if not target_dir.exists():
            shutil.move(str(staged), str(target_dir))
            _fsync_dir(str(root))

        manifest_path = target_dir / "manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(f"published manifest missing: {manifest_path}")

        digest = file_sha256(manifest_path)
        pointer_payload = {
            "snapshot_id": manifest.snapshot_id,
            "manifest_sha256": digest,
        }
        pointer_file.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(pointer_file, pointer_payload, canonical=True)

    return target_dir


def read_pointer(
    snapshots_root: Path | str, branch_name: str | None = None
) -> dict[str, Any] | None:
    """Return dictionary payload of pointer file, or None if missing."""
    path = pointer_path_for(Path(snapshots_root), branch_name)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def checkout_tip(
    snapshots_root: Path | str,
    target_snapshot_id: str,
    *,
    branch_name: str | None = None,
) -> Path:
    """Atomically swing pointer to a target snapshot under exclusive lock."""
    root = Path(snapshots_root)
    target_manifest = root / target_snapshot_id / "manifest.json"
    if not target_manifest.is_file():
        raise FileNotFoundError(f"target snapshot manifest missing: {target_manifest}")
    lock_file = root / ".publication.lock"
    pointer_file = pointer_path_for(root, branch_name)
    digest = file_sha256(target_manifest)
    with PublicationLock(lock_file):
        pointer_payload = {
            "snapshot_id": target_snapshot_id,
            "manifest_sha256": digest,
        }
        pointer_file.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(pointer_file, pointer_payload, canonical=True)
    return pointer_file


def list_branches(snapshots_root: Path | str) -> list[str]:
    """Return all branch names with existing pointer files."""
    root = Path(snapshots_root)
    branches: list[str] = []
    if pointer_path_for(root).is_file():
        branches.append("current")
    branches_dir = root / "branches"
    if branches_dir.is_dir():
        for b_dir in sorted(branches_dir.iterdir()):
            if (b_dir / "pointer.json").is_file():
                branches.append(b_dir.name)
    return branches


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
    """Delete a named branch pointer under publication lock."""
    if branch_name in ("current", ""):
        raise ValueError("cannot delete 'current' branch")
    root = Path(snapshots_root)
    pointer = pointer_path_for(root, branch_name)
    lock_file = root / ".publication.lock"
    with PublicationLock(lock_file):
        if not pointer.is_file():
            return False
        pointer.unlink()
        pointer.parent.rmdir()
        return True


__all__ = [
    "PublicationLock",
    "PublicationLockError",
    "StaleParentError",
    "checkout_tip",
    "create_branch",
    "delete_branch",
    "list_branches",
    "pointer_path_for",
    "publish_node",
    "read_pointer",
    "read_pointer_id",
]
