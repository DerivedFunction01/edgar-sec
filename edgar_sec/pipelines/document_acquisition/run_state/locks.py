from __future__ import annotations

import json
import os
import socket
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Self

from edgar_sec.pipelines.document_acquisition.models import RunLockInfo


class RunLockError(RuntimeError):
    pass


class RunLock:
    def __init__(
        self,
        lock_path: Path,
        run_id: str,
        *,
        stale_local_lock_confirmed: bool = False,
    ) -> None:
        self.path = Path(lock_path)
        self.token = uuid.uuid4().hex
        self.run_id = run_id
        self.host = socket.gethostname()
        self.pid = os.getpid()
        self.started_at_utc = datetime.now(UTC).isoformat(timespec="seconds")
        payload = self._payload()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._create(self.path, payload)
        except FileExistsError:
            self._recover_existing(stale_local_lock_confirmed, payload)

    def _payload(self) -> bytes:
        return json.dumps(
            {
                "run_id": self.run_id,
                "host": self.host,
                "pid": self.pid,
                "started_at_utc": self.started_at_utc,
                "owner_token": self.token,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @staticmethod
    def _create(path: Path, payload: bytes) -> None:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _recover_existing(self, confirmed: bool, payload: bytes) -> None:
        existing = self._read_lock()
        if existing.get("run_id") != self.run_id:
            raise RunLockError("existing lock belongs to a different run")
        if existing.get("host") != self.host:
            raise RunLockError("remote-host locks require operator recovery")
        pid = existing.get("pid")
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            raise RunLockError("existing run lock has an invalid PID")
        if self._pid_is_alive(pid):
            raise RunLockError(f"run is already locked: {self.path}")
        if not confirmed:
            raise RunLockError(
                "stale local lock recovery requires explicit confirmation"
            )
        recovery_path = self.path.with_name(f"{self.path.name}.recovery")
        try:
            self._create(recovery_path, payload)
        except FileExistsError as error:
            raise RunLockError("stale-lock recovery is already active") from error
        try:
            current = self._read_lock()
            if current.get("owner_token") != existing.get("owner_token"):
                raise RunLockError("run lock changed during stale recovery")
            self.path.unlink()
            try:
                self._create(self.path, payload)
            except FileExistsError as error:
                raise RunLockError("run lock was acquired concurrently") from error
        finally:
            recovery_path.unlink(missing_ok=True)

    def _read_lock(self) -> dict[str, object]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise RunLockError("existing run lock is unreadable") from error
        if not isinstance(value, dict) or not isinstance(value.get("owner_token"), str):
            raise RunLockError("existing run lock is malformed")
        return value

    @staticmethod
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

    def close(self) -> None:
        try:
            current = self._read_lock()
        except RunLockError:
            return
        if current.get("owner_token") == self.token:
            self.path.unlink(missing_ok=True)

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()


def inspect_run_lock(
    lock_path: Path, *, expected_run_id: str | None = None
) -> RunLockInfo | None:
    path = Path(lock_path)
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise RunLockError("run lock path is unsafe")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RunLockError("existing run lock is unreadable") from error
    if not isinstance(value, dict):
        raise RunLockError("existing run lock is malformed")
    run_id = value.get("run_id")
    host = value.get("host")
    pid = value.get("pid")
    started_at_utc = value.get("started_at_utc")
    owner_token = value.get("owner_token")
    if (
        not isinstance(host, str)
        or not host
        or not isinstance(run_id, str)
        or not run_id
        or not isinstance(pid, int)
        or isinstance(pid, bool)
        or pid <= 0
        or not isinstance(started_at_utc, str)
        or not started_at_utc
        or not isinstance(owner_token, str)
        or not owner_token
    ):
        raise RunLockError("existing run lock is malformed")
    if expected_run_id is not None and run_id != expected_run_id:
        raise RunLockError("run lock belongs to a different run")
    if host == socket.gethostname() and not RunLock._pid_is_alive(pid):
        return None
    return RunLockInfo(
        host=host,
        pid=pid,
        started_at_utc=started_at_utc,
        owner_token=owner_token,
    )


__all__ = ["RunLock", "RunLockError", "inspect_run_lock"]
