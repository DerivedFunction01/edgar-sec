"""Exclusive run ownership and explicit stale-lock recovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.pipelines.document_inventory.paths import inventory_run_paths
from edgar_sec.pipelines.document_inventory.run_lock import RunLock, RunLockError


def test_same_run_lock_rejects_competitors(tmp_path: Path) -> None:
    paths = inventory_run_paths(tmp_path, "lock-run")
    with RunLock(paths, stale_lock_confirmed=False):
        with pytest.raises(RunLockError, match="already locked"):
            RunLock(paths, stale_lock_confirmed=False)
        assert paths.lock_path().is_file()
    assert not paths.lock_path().exists()


def test_different_run_ids_have_independent_locks(tmp_path: Path) -> None:
    first = inventory_run_paths(tmp_path, "first-run")
    second = inventory_run_paths(tmp_path, "second-run")
    with (
        RunLock(first, stale_lock_confirmed=False),
        RunLock(second, stale_lock_confirmed=False),
    ):
        assert first.lock_path().is_file()
        assert second.lock_path().is_file()


def test_stale_lock_requires_explicit_operator_confirmation(tmp_path: Path) -> None:
    paths = inventory_run_paths(tmp_path, "stale-run")
    paths.lock_path().parent.mkdir(parents=True, exist_ok=True)
    paths.lock_path().write_text('{"pid": 1, "host": "stale"}', encoding="utf-8")

    with pytest.raises(RunLockError, match="explicit operator confirmation"):
        RunLock(paths, stale_lock_confirmed=False)
    assert paths.lock_path().is_file()

    with RunLock(paths, stale_lock_confirmed=True):
        assert '"token"' in paths.lock_path().read_text(encoding="utf-8")
    assert not paths.lock_path().exists()
