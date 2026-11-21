from __future__ import annotations

import json
from argparse import Namespace

from edgar_sec.pipelines.document_acquisition import cli
from edgar_sec.pipelines.document_acquisition.commands import publish
from edgar_sec.pipelines.document_acquisition.snapshot.errors import (
    RunNotPublishableError,
)
from edgar_sec.pipelines.document_acquisition.snapshot.models import (
    PublicationReceipt,
    SnapshotPublication,
)


def test_publish_command_success(capsys, tmp_path, monkeypatch) -> None:
    receipt = PublicationReceipt(
        receipt_schema_version="1",
        snapshot_id="snap-123",
        run_id="run-1",
        branch="main",
        published_at_utc="2026-10-14T00:00:00Z",
        adopted_payload_count=1,
        adopted_payload_bytes=100,
        relation_row_counts={"target_results": 1},
    )

    def fake_publish(paths, run_id, **kwargs):
        return SnapshotPublication.published(run_id, "snap-123", receipt)

    monkeypatch.setattr(publish, "publish_acquisition_run", fake_publish)
    result = cli.main(
        ["publish", "--run-id", "run-1", "--artifacts", str(tmp_path), "--json"]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "publish"
    assert payload["status"] == "published"
    assert payload["snapshot_id"] == "snap-123"


def test_publish_command_handles_error(capsys, tmp_path, monkeypatch) -> None:
    def fake_publish_err(paths, run_id, **kwargs):
        raise RunNotPublishableError("run is not ready")

    monkeypatch.setattr(publish, "publish_acquisition_run", fake_publish_err)
    result = cli.main(
        ["publish", "--run-id", "run-1", "--artifacts", str(tmp_path), "--json"]
    )

    assert result == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "publish"
    assert payload["status"] == "error"
    assert "run is not ready" in payload["error"]


def test_publish_command_text_output(capsys, tmp_path, monkeypatch) -> None:
    def fake_publish(paths, run_id, **kwargs):
        return SnapshotPublication.already_published(run_id, "snap-123")

    monkeypatch.setattr(publish, "publish_acquisition_run", fake_publish)
    result = cli.main(["publish", "--run-id", "run-1", "--artifacts", str(tmp_path)])

    assert result == 0
    assert (
        "Publish run-1: already_published; snapshot snap-123" in capsys.readouterr().out
    )
