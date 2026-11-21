from __future__ import annotations

import argparse

from edgar_sec.pipelines.document_inventory.commands import (
    inspect_snapshot as command,
)


def test_inspect_snapshot_reports_json(monkeypatch, capsys, tmp_path) -> None:
    report = {"snapshot_id": "snapshot-a", "parts": []}
    monkeypatch.setattr(command, "inspect_snapshot", lambda *_args, **_kwargs: report)
    args = argparse.Namespace(
        artifacts_root=str(tmp_path), snapshot="current", branch="main", json=True
    )

    assert command.cmd_inspect_snapshot(args) == 0
    assert '"snapshot_id": "snapshot-a"' in capsys.readouterr().out
