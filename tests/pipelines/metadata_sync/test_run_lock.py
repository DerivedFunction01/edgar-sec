"""Lock ownership, stale recovery, and the refusals that protect a live run."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path

import pytest

from edgar_sec.pipelines.metadata_sync.run_lock import (
    RunLock,
    RunLockError,
    read_lock_owner,
)

DEAD_PID = 2_000_000_000


def _write_lock(path: Path, *, host: str, pid: int) -> None:
    path.write_text(
        json.dumps({"token": "prior-token", "pid": pid, "host": host}),
        encoding="utf-8",
    )


def test_a_lock_records_its_holder_and_releases_on_close(tmp_path: Path) -> None:
    path = tmp_path / "run.lock"
    lock = RunLock(path, stale_lock_confirmed=False)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["pid"] == os.getpid()
    assert payload["host"] == socket.gethostname()
    assert payload["token"] == lock.token
    lock.close()
    assert not path.exists()


def test_a_live_local_owner_is_never_displaced(tmp_path: Path) -> None:
    """The attestation covers a stale holder, not a running one."""
    path = tmp_path / "run.lock"
    _write_lock(path, host=socket.gethostname(), pid=os.getpid())
    with pytest.raises(RunLockError, match="already locked"):
        RunLock(path, stale_lock_confirmed=True)
    assert json.loads(path.read_text(encoding="utf-8"))["token"] == "prior-token"


def test_a_stale_lock_requires_explicit_confirmation(tmp_path: Path) -> None:
    path = tmp_path / "run.lock"
    _write_lock(path, host=socket.gethostname(), pid=DEAD_PID)
    with pytest.raises(RunLockError, match="explicit operator confirmation"):
        RunLock(path, stale_lock_confirmed=False)
    assert path.is_file()


def test_a_confirmed_stale_lock_is_taken_over(tmp_path: Path) -> None:
    path = tmp_path / "run.lock"
    _write_lock(path, host=socket.gethostname(), pid=DEAD_PID)
    lock = RunLock(path, stale_lock_confirmed=True)
    assert json.loads(path.read_text(encoding="utf-8"))["token"] == lock.token
    lock.close()
    assert not path.exists()


def test_a_remote_lock_is_taken_over_only_on_confirmation(tmp_path: Path) -> None:
    """A remote holder's liveness is unknowable here, so the attestation decides."""
    path = tmp_path / "run.lock"
    _write_lock(path, host="remote.example", pid=DEAD_PID)
    with pytest.raises(RunLockError, match="explicit operator confirmation"):
        RunLock(path, stale_lock_confirmed=False)
    lock = RunLock(path, stale_lock_confirmed=True)
    assert json.loads(path.read_text(encoding="utf-8"))["token"] == lock.token
    lock.close()


def test_a_malformed_lock_is_not_evidence_of_staleness(tmp_path: Path) -> None:
    path = tmp_path / "run.lock"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(RunLockError, match="malformed"):
        RunLock(path, stale_lock_confirmed=True)
    assert path.is_file()


def test_a_lock_with_an_impossible_pid_is_not_evidence_of_staleness(
    tmp_path: Path,
) -> None:
    path = tmp_path / "run.lock"
    _write_lock(path, host=socket.gethostname(), pid=0)
    with pytest.raises(RunLockError, match="malformed"):
        RunLock(path, stale_lock_confirmed=True)


def test_the_lock_is_released_when_the_body_raises(tmp_path: Path) -> None:
    path = tmp_path / "run.lock"
    with pytest.raises(ZeroDivisionError):
        with RunLock(path, stale_lock_confirmed=False):
            raise ZeroDivisionError
    assert not path.exists()


def test_read_lock_owner_reports_the_holder(tmp_path: Path) -> None:
    path = tmp_path / "run.lock"
    assert read_lock_owner(path) is None
    _write_lock(path, host="remote.example", pid=42)
    owner = read_lock_owner(path)
    assert owner is not None
    assert (owner.pid, owner.host, owner.token) == (42, "remote.example", "prior-token")
