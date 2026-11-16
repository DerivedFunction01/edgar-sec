"""Pins for the lock-file creation primitive homed in infra and the RunLock
policy split: metadata_sync never displaces a live local holder, inventory
takes over on operator confirmation alone.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import stat

import pytest

from edgar_sec.infra.run_lock import create_lock_file
from edgar_sec.pipelines.document_inventory.paths import InventoryRunPaths
from edgar_sec.pipelines.document_inventory.run_state.run_lock import (
    RunLock as InventoryRunLock,
)
from edgar_sec.pipelines.metadata_sync.run_lock import (
    RunLock as MetadataRunLock,
    RunLockError,
)


def test_create_lock_file_writes_payload_exclusively(tmp_path: Path) -> None:
    target = tmp_path / "run.lock"
    create_lock_file(target, b"payload")
    assert target.read_bytes() == b"payload"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        create_lock_file(target, b"other")
    assert target.read_bytes() == b"payload"


def _live_holder_payload() -> bytes:
    return json.dumps(
        {"token": "other", "pid": os.getpid(), "host": socket.gethostname()},
        sort_keys=True,
    ).encode("utf-8")


def test_metadata_lock_refuses_a_live_local_holder(tmp_path: Path) -> None:
    lock_path = tmp_path / "run.lock"
    lock_path.write_bytes(_live_holder_payload())
    with pytest.raises(RunLockError):
        MetadataRunLock(lock_path, stale_lock_confirmed=True)


def test_inventory_lock_takes_over_on_confirmation_alone(
    tmp_path: Path,
) -> None:
    paths = InventoryRunPaths(tmp_path, "run-1")
    lock_path = paths.lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_bytes(_live_holder_payload())
    lock = InventoryRunLock(paths, stale_lock_confirmed=True)
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        assert data["token"] == lock.token
    finally:
        lock.close()
    assert not lock_path.exists()
