"""Exclusive coordinator ownership for one metadata sync run."""

from __future__ import annotations

import json
import os
import socket
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Self

from edgar_sec.infra.storage.atomic import _fsync_dir

__all__ = ["LockOwner", "RunLock", "RunLockError", "read_lock_owner"]


class RunLockError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LockOwner:
    """The holder a lock file names."""

    pid: int
    host: str
    token: str


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    except OverflowError:
        return True
    return True


def read_lock_owner(lock_path: Path) -> LockOwner | None:
    """The holder a lock file names, or ``None`` when no lock file exists.

    A lock that cannot be read is not evidence of staleness, so it refuses.
    """
    path = Path(lock_path)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise RunLockError(f"run lock is unreadable: {path}") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RunLockError(f"run lock is malformed: {path}") from exc
    if not isinstance(payload, dict):
        raise RunLockError(f"run lock is malformed: {path}")
    pid = payload.get("pid")
    host = payload.get("host")
    token = payload.get("token")
    if (
        not isinstance(pid, int)
        or isinstance(pid, bool)
        or pid <= 0
        or not isinstance(host, str)
        or not host
        or not isinstance(token, str)
        or not token
    ):
        raise RunLockError(f"run lock is malformed: {path}")
    return LockOwner(pid=pid, host=host, token=token)


class RunLock:
    def __init__(self, lock_path: Path, *, stale_lock_confirmed: bool) -> None:
        self.path = Path(lock_path)
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
            self._recover_existing(stale_lock_confirmed, payload)

    def _recover_existing(self, confirmed: bool, payload: bytes) -> None:
        """Take over a lock whose holder has stopped.

        A live holder on this host is never displaced: the confirmation attests
        a stale holder, it does not override a running one.
        """
        owner = read_lock_owner(self.path)
        if owner is None:
            self._acquire_after_release(payload)
            return
        if owner.host == socket.gethostname() and _pid_is_alive(owner.pid):
            raise RunLockError(f"run is already locked: {self.path}")
        if not confirmed:
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

    def _acquire_after_release(self, payload: bytes) -> None:
        """The holder released between the failed create and the read."""
        try:
            self._create(payload)
        except FileExistsError as exc:
            raise RunLockError(
                f"run lock was acquired concurrently: {self.path}"
            ) from exc

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
