from __future__ import annotations

from argparse import Namespace

import pytest

from edgar_sec.pipelines.document_inventory.commands import publish as publish_command
from edgar_sec.pipelines.document_inventory.run_state import InventoryRunStatus


def _status(state: str, *, valid: bool = True) -> InventoryRunStatus:
    return InventoryRunStatus(
        run_id="run-1",
        state=state,
        valid=valid,
        error=None if valid else "invalid run",
        catalog_plan_id="plan-1",
        base_snapshot_id="snapshot-1",
        work_order_rows=1,
        expected_chunks=1,
        committed_chunks=1,
        outstanding_chunks=0,
        pending_accessions=0,
        invalid_chunks=0,
        retryable_failures=0,
        refused_outcomes=0,
        locked=False,
        lock_metadata=None,
        published_snapshot_id=("snapshot-published" if state == "published" else None),
    )


def test_publish_already_published_does_not_open_writer(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        publish_command, "load_run_status", lambda *_args: _status("published")
    )
    monkeypatch.setattr(
        publish_command,
        "publish_committed_chunks",
        lambda *_args, **_kwargs: pytest.fail("published run re-entered writer"),
    )
    args = Namespace(
        artifacts_root=str(tmp_path),
        run_id="run-1",
        branch="main",
        expected_branch_tip=None,
        json=False,
    )

    assert publish_command.cmd_publish(args) == 0
    assert "already published" in capsys.readouterr().out


def test_publish_refuses_incomplete_run_before_mutation(tmp_path, monkeypatch):
    monkeypatch.setattr(
        publish_command, "load_run_status", lambda *_args: _status("projected")
    )
    monkeypatch.setattr(
        publish_command,
        "load_run_state",
        lambda *_args: pytest.fail("incomplete run entered publication"),
    )
    args = Namespace(
        artifacts_root=str(tmp_path),
        run_id="run-1",
        branch="main",
        expected_branch_tip=None,
        json=False,
    )

    with pytest.raises(ValueError, match="not publishable"):
        publish_command.cmd_publish(args)
