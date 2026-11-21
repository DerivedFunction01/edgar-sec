from __future__ import annotations

import json
from unittest.mock import MagicMock

import pyarrow as pa

from edgar_sec.pipelines.document_acquisition import cli
from edgar_sec.pipelines.document_acquisition.commands import snapshot


def test_snapshot_status_command(capsys, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        snapshot,
        "get_snapshot_status",
        lambda paths, branch_name: {
            "branch": branch_name,
            "published": True,
            "snapshot_id": "snap-123",
            "kind": "snapshot",
            "lineage_depth": 1,
            "relation_counts": {"target_results": 1},
        },
    )
    result = cli.main(["snapshot", "status", "--artifacts", str(tmp_path), "--json"])

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "snapshot status"
    assert payload["published"] is True
    assert payload["snapshot_id"] == "snap-123"


def test_snapshot_query_command(capsys, tmp_path, monkeypatch) -> None:
    table = pa.Table.from_pydict({"target_id": ["t-1"], "outcome": ["completed"]})
    monkeypatch.setattr(
        snapshot,
        "query_snapshot_relation",
        lambda paths, relation, **kwargs: table,
    )
    result = cli.main(
        [
            "snapshot",
            "query",
            "--relation",
            "target_results",
            "--artifacts",
            str(tmp_path),
            "--json",
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "snapshot query"
    assert payload["relation"] == "target_results"
    assert payload["row_count"] == 1
    assert payload["rows"] == [{"target_id": "t-1", "outcome": "completed"}]


def test_snapshot_list_command(capsys, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        snapshot,
        "list_snapshots",
        lambda paths: [
            {
                "snapshot_id": "snap-1",
                "kind": "snapshot",
                "parent_snapshot_id": None,
            }
        ],
    )
    result = cli.main(["snapshot", "list", "--artifacts", str(tmp_path), "--json"])

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "snapshot list"
    assert payload["count"] == 1
    assert payload["snapshots"][0]["snapshot_id"] == "snap-1"


def test_snapshot_status_error_handling(capsys, tmp_path, monkeypatch) -> None:
    def fake_error(*args, **kwargs):
        raise ValueError("catalog corrupted")

    monkeypatch.setattr(snapshot, "get_snapshot_status", fake_error)
    result = cli.main(["snapshot", "status", "--artifacts", str(tmp_path), "--json"])

    assert result == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "snapshot status"
    assert payload["status"] == "error"
    assert "catalog corrupted" in payload["error"]
