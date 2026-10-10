from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from edgar_sec.pipelines.document_acquisition import cli, operator


def test_parser_registers_independent_acquisition_tracks() -> None:
    parser = cli.build_parser()

    for args in (
        ["project", "--plan-id", "plan-1"],
        ["status"],
        ["run", "--run-id", "run-1"],
        ["process", "--run-id", "run-1"],
        ["publish", "--run-id", "run-1"],
        ["fixture", "capture", "--fixture-id", "f-1", "--run-id", "run-1"],
        ["review", "build", "--run-id", "run-1"],
        ["snapshot", "audit"],
    ):
        assert parser.parse_args(args)


def test_todo_command_returns_stable_json_without_work(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = cli.main(["run", "--run-id", "run-1", "--json"])

    assert result == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "command": "run",
        "implemented": False,
        "message": "This command track is not implemented; no work was performed.",
        "status": "not_implemented",
        "track": "S9 network acquisition",
    }


def test_project_command_delegates_to_offline_service(
    capsys: pytest.CaptureFixture[str], tmp_path, monkeypatch
) -> None:
    calls = []
    manifest = {
        "target_plan_id": "dplan-1",
        "target_plan_digest": "a" * 64,
    }

    def fake_project(plan_id, *, paths):
        calls.append((plan_id, paths.artifacts_root))
        return SimpleNamespace(
            run_id="acq_1",
            manifest=manifest,
            executable_count=1,
            skipped_count=2,
            work_order_sha256="b" * 64,
            reused=False,
        )

    monkeypatch.setattr(cli, "project_acquisition_run", fake_project)
    result = cli.main(
        ["project", "--plan-id", "dplan-1", "--artifacts", str(tmp_path), "--json"]
    )

    assert result == 0
    assert calls == [("dplan-1", tmp_path.resolve())]
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "command": "project",
        "executable_count": 1,
        "reused": False,
        "run_id": "acq_1",
        "skipped_count": 2,
        "status": "ready",
        "target_plan_digest": "a" * 64,
        "target_plan_id": "dplan-1",
        "work_order_sha256": "b" * 64,
    }


def test_publish_todo_reports_gate_and_does_not_claim_publication(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = cli.main(["publish", "--run-id", "run-1", "--json"])

    assert result == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "blocked_by_gate"
    assert "representative S9/S10 evidence and explicit approval" in payload["message"]


def test_review_and_snapshot_commands_keep_separate_placeholder_handlers(
    capsys: pytest.CaptureFixture[str],
) -> None:
    review_result = cli.main(["review", "build", "--run-id", "run-1", "--json"])
    review = json.loads(capsys.readouterr().out)
    snapshot_result = cli.main(["snapshot", "status", "--json"])
    snapshot = json.loads(capsys.readouterr().out)

    assert review_result == snapshot_result == 2
    assert review["command"] == "review build"
    assert snapshot["command"] == "snapshot status"
    assert snapshot["status"] == "not_implemented"
    assert "No acquisition snapshot is published" in snapshot["message"]


def test_invalid_worker_count_is_refused_by_cli_parser() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["run", "--run-id", "run-1", "--workers", "0"])


def test_operator_dispatches_command_args_through_same_cli(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = operator.main(["project", "--plan-id", "plan-1", "--json"])

    assert result == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "project"
    assert payload["status"] == "error"
