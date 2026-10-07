"""Exclusive coordinator ownership for one metadata sync run."""

from __future__ import annotations

import json
import os
import socket
import uuid
from pathlib import Path
from types import TracebackType
from typing import Self

from edgar_sec.infra.storage.atomic import _fsync_dir

__all__ = ["RunLock", "RunLockError"]


class RunLockError(RuntimeError):
    pass


class RunLock:
    def __init__(self, lock_path: Path, *, stale_lock_confirmed: bool) -> None:
        self.path = lock_path
        self.token = uuid.uuid4().hex
        payload = json.dumps(
            {
                "token": self.token,
                "pid": os.getpid(),
                "host": socket.gethostname(),
            },
            sort_keys=True,
        ).encode("utf-8")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._create(payload)
        except FileExistsError:
            if not stale_lock_confirmed:
                raise RunLockError(
                    f"run is already locked: {self.path}; stale recovery requires "
                    "explicit operator confirmation"
                )
            recovery_path = self.path.with_name(f"{self.path.name}.recovery")
            try:
                self._create_at(recovery_path, payload)
            except FileExistsError as exc:
                raise RunLockError(
                    f"stale-lock recovery is already active: {self.path}"
                ) from exc
            try:
                self.path.unlink(missing_ok=True)
                self._create(payload)
            except FileExistsError as exc:
                raise RunLockError(
                    f"run lock was acquired concurrently: {self.path}"
                ) from exc
            finally:
                recovery_path.unlink(missing_ok=True)
                _fsync_dir(str(self.path.parent))

    def _create(self, payload: bytes) -> None:
        self._create_at(self.path, payload)

    @staticmethod
    def _create_at(path: Path, payload: bytes) -> None:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _fsync_dir(str(path.parent))

    def close(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if isinstance(data, dict) and data.get("token") == self.token:
            self.path.unlink(missing_ok=True)
            _fsync_dir(str(self.path.parent))

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()
