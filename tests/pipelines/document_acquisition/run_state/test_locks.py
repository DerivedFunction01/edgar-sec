import json
import os
import socket

import pytest

from edgar_sec.pipelines.document_acquisition.run_state.locks import (
    RunLock,
    RunLockError,
)


def _write_lock(path, *, host, pid, token="prior-token") -> None:
    path.write_text(
        json.dumps(
            {
                "run_id": "run-id",
                "host": host,
                "pid": pid,
                "started_at_utc": "2025-01-01T00:00:00Z",
                "owner_token": token,
            }
        ),
        encoding="utf-8",
    )


def test_lock_creation_and_release_require_owner_token(tmp_path) -> None:
    path = tmp_path / "run.lock"
    lock = RunLock(path, "run-id")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["run_id"] == "run-id"
    assert payload["host"] == socket.gethostname()
    assert payload["pid"] == os.getpid()
    assert payload["owner_token"] == lock.token

    _write_lock(path, host=socket.gethostname(), pid=os.getpid(), token="other")
    lock.close()
    assert path.is_file()


def test_existing_active_local_lock_blocks_even_with_confirmation(tmp_path) -> None:
    path = tmp_path / "run.lock"
    _write_lock(path, host=socket.gethostname(), pid=os.getpid())
    with pytest.raises(RunLockError, match="already locked"):
        RunLock(path, "run-id", stale_local_lock_confirmed=True)


def test_stale_local_lock_requires_explicit_confirmation(tmp_path) -> None:
    path = tmp_path / "run.lock"
    _write_lock(path, host=socket.gethostname(), pid=2_000_000_000)
    with pytest.raises(RunLockError, match="explicit confirmation"):
        RunLock(path, "run-id")

    lock = RunLock(path, "run-id", stale_local_lock_confirmed=True)
    assert json.loads(path.read_text(encoding="utf-8"))["owner_token"] == lock.token
    lock.close()
    assert not path.exists()


def test_remote_lock_never_uses_local_pid_as_stale_evidence(tmp_path) -> None:
    path = tmp_path / "run.lock"
    _write_lock(path, host="remote.example", pid=2_000_000_000)
    with pytest.raises(RunLockError, match="remote-host"):
        RunLock(path, "run-id", stale_local_lock_confirmed=True)


def test_malformed_pid_is_not_reclaimed_as_stale(tmp_path) -> None:
    path = tmp_path / "run.lock"
    _write_lock(path, host=socket.gethostname(), pid=-1)
    with pytest.raises(RunLockError, match="invalid PID"):
        RunLock(path, "run-id", stale_local_lock_confirmed=True)


def test_lock_context_releases_owned_file(tmp_path) -> None:
    path = tmp_path / "run.lock"
    with RunLock(path, "run-id"):
        assert path.is_file()
    assert not path.exists()
