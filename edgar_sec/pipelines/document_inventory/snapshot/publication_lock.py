"""Serialize snapshot installation and pointer updates per inventory root."""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
from types import TracebackType
from typing import Self

from edgar_sec.infra.storage.atomic import _fsync_dir
from edgar_sec.pipelines.document_inventory.paths import InventoryPaths

__all__ = ["PublicationLock", "PublicationLockError"]


class PublicationLockError(RuntimeError):
    """A non-blocking publication lock request found another writer."""


class PublicationLock:
    def __init__(self, paths: InventoryPaths, *, blocking: bool = True) -> None:
        self.path = paths.publication_lock_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        operation = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        try:
            fcntl.flock(self._descriptor, operation)
        except BlockingIOError as exc:
            os.close(self._descriptor)
            self._descriptor = -1
            raise PublicationLockError(
                f"snapshot publication is locked: {self.path}"
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
