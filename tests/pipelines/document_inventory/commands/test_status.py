from __future__ import annotations

from argparse import Namespace

from edgar_sec.pipelines.document_inventory.commands import status as status_command
from edgar_sec.pipelines.document_inventory.run_state.run_state import (
    InventoryRunStatus,
)


def test_status_renders_lock_owner_and_pending_counts(tmp_path, monkeypatch, capsys):
    status = InventoryRunStatus(
        run_id="run-1",
        state="running",
        valid=True,
        error=None,
        catalog_plan_id="plan-1",
        base_snapshot_id="snapshot-1",
        work_order_rows=3,
        expected_chunks=2,
        committed_chunks=1,
        outstanding_chunks=1,
        pending_accessions=2,
        invalid_chunks=0,
        retryable_failures=0,
        refused_outcomes=0,
        locked=True,
        lock_metadata={"pid": 41, "host": "worker"},
        published_snapshot_id=None,
    )
    monkeypatch.setattr(
        status_command,
        "discover_run_statuses",
        lambda _root: (status,),
    )

    assert (
        status_command.cmd_status(
            Namespace(artifacts_root=str(tmp_path), run_id=None, json=False)
        )
        == 0
    )
    output = capsys.readouterr().out
    assert output.startswith("Inventory Status\n")
    assert "pending_accessions" in output
    assert "outstanding_chunks" in output
    assert "pid=41 host=worker" in output
    assert "snapshot-1" in output


def test_status_specific_invalid_run_returns_nonzero(tmp_path, monkeypatch, capsys):
    status = InventoryRunStatus(
        run_id="run-bad",
        state="invalid",
        valid=False,
        error="invalid manifest",
        catalog_plan_id=None,
        base_snapshot_id=None,
        work_order_rows=0,
        expected_chunks=0,
        committed_chunks=0,
        outstanding_chunks=0,
        pending_accessions=0,
        invalid_chunks=0,
        retryable_failures=0,
        refused_outcomes=0,
        locked=False,
        lock_metadata=None,
        published_snapshot_id=None,
    )
    monkeypatch.setattr(status_command, "load_run_status", lambda *_args: status)

    assert (
        status_command.cmd_status(
            Namespace(artifacts_root=str(tmp_path), run_id="run-bad", json=False)
        )
        == 1
    )
    assert "invalid manifest" in capsys.readouterr().out


def _status(run_id, **overrides):
    values = {
        "run_id": run_id,
        "state": "ready",
        "valid": True,
        "error": None,
        "catalog_plan_id": "plan-1",
        "base_snapshot_id": "snapshot-1",
        "work_order_rows": 3,
        "expected_chunks": 2,
        "committed_chunks": 2,
        "outstanding_chunks": 0,
        "pending_accessions": 0,
        "invalid_chunks": 0,
        "retryable_failures": 0,
        "refused_outcomes": 0,
        "locked": False,
        "lock_metadata": None,
        "published_snapshot_id": None,
    }
    values.update(overrides)
    return InventoryRunStatus(**values)


def test_status_text_list_renders_one_grid_row_per_run(tmp_path, monkeypatch, capsys):
    statuses = (
        _status(
            "run-1",
            state="running",
            committed_chunks=1,
            locked=True,
            lock_metadata={"pid": 41, "host": "worker"},
        ),
        _status(
            "run-2", base_snapshot_id=None, retryable_failures=1, refused_outcomes=2
        ),
    )
    monkeypatch.setattr(status_command, "discover_run_statuses", lambda _root: statuses)

    assert (
        status_command.cmd_status(
            Namespace(artifacts_root=str(tmp_path), run_id=None, json=False)
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "run_id" in output and "chunks" in output and "base" in output
    assert "run-1" in output and "1/2" in output and "pid=41 host=worker" in output
    assert "run-2" in output and "(empty)" in output


def test_status_text_no_runs_renders_prose_row(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(status_command, "discover_run_statuses", lambda _root: ())

    assert (
        status_command.cmd_status(
            Namespace(artifacts_root=str(tmp_path), run_id=None, json=False)
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "Inventory Status" in output
    assert "No projected inventory runs" in output
