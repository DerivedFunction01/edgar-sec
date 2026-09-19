"""End-to-end tests for Phase 2.5 CLI."""

from __future__ import annotations

import importlib
import json
import uuid
from pathlib import Path

import pytest

cli = importlib.import_module("phases.025_webpage_storage.cli")


def test_cli_preview(phase02_bundle: Path, capsys: pytest.CaptureFixture[str]):
    code = cli.main(["preview", "--plan-dir", str(phase02_bundle)])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["locator_count"] == 2
    assert data["occurrence_count"] == 2


def test_cli_run_multi_worker_and_status(
    phase02_bundle: Path,
    fixture_database: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    out_dir = tmp_path / "cli_out"
    code = cli.main(
        [
            "run",
            "--plan-dir",
            str(phase02_bundle),
            "--output-dir",
            str(out_dir),
            "--mode",
            "fixture",
            "--fixtures",
            fixture_database.parent.name,
            "--run-id",
            f"cli-multi-run-{uuid.uuid4().hex}",
            "--workers",
            "2",
            "--chunk-size",
            "1",
        ]
    )
    assert code == 0
    captured = capsys.readouterr()
    run_data = json.loads(captured.out)
    assert run_data["occurrence_count"] == 2
    assert len(run_data["chunks"]) == 2

    partition_db = out_dir / "partition-00001.sqlite"
    assert partition_db.is_file()

    # Test status
    status_code = cli.main(["status", "--database", str(partition_db)])
    assert status_code == 0
    status_captured = capsys.readouterr()
    status_data = json.loads(status_captured.out)
    assert status_data["exists"] is True
    assert status_data["blobs"] == 2
    assert status_data["occurrences"] == 2
    assert status_data["committed_chunks"] == 2
    assert status_data["failures"] == 0


def test_cli_run_no_progress(
    phase02_bundle: Path,
    fixture_database: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
):
    out_dir = tmp_path / "cli_no_prog_out"
    code = cli.main(
        [
            "run",
            "--plan-dir",
            str(phase02_bundle),
            "--output-dir",
            str(out_dir),
            "--mode",
            "fixture",
            "--fixtures",
            fixture_database.parent.name,
            "--run-id",
            f"cli-no-prog-run-{uuid.uuid4().hex}",
            "--no-progress",
        ]
    )
    assert code == 0
    captured = capsys.readouterr()
    run_data = json.loads(captured.out)
    assert run_data["occurrence_count"] == 2


def test_cli_run_derives_run_namespaced_partition_output(
    phase02_bundle: Path,
    fixture_database: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    artifacts_root = tmp_path / "artifacts"
    monkeypatch.setenv("ARTIFACTS_ROOT", str(artifacts_root))
    run_id = f"derived-run-{uuid.uuid4().hex}"
    code = cli.main(
        [
            "run",
            "--plan-dir",
            str(phase02_bundle),
            "--mode",
            "fixture",
            "--fixtures",
            str(fixture_database),
            "--run-id",
            run_id,
            "--no-progress",
        ]
    )
    assert code == 0
    run_data = json.loads(capsys.readouterr().out)
    expected = (
        artifacts_root
        / "manifests"
        / "webpage_storage"
        / "partition_artifacts"
        / run_id
        / "partition-00001.sqlite"
    )
    assert Path(run_data["partition_db"]) == expected
    assert expected.is_file()
    assert expected.with_name(expected.name + ".manifest.json").is_file()

    status_code = cli.main(["status", "--run-id", run_id])
    assert status_code == 0
    status = json.loads(capsys.readouterr().out)
    assert status["snapshot_eligible"] is True

    merge_code = cli.main(["merge-to-snapshot", "--run-id", run_id])
    assert merge_code == 0
    manifest = json.loads(capsys.readouterr().out)
    assert manifest["dataset"] == "normalized_documents"
