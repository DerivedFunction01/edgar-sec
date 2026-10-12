from __future__ import annotations

import json

import pytest

from edgar_sec.pipelines.document_acquisition import cli, operator


def test_parser_registers_independent_acquisition_tracks() -> None:
    parser = cli.build_parser()

    for args in (
        ["project", "--plan-id", "plan-1"],
        ["status"],
        ["status", "--run-id", "run-1", "--target-id", "target-1"],
        ["run", "--run-id", "run-1", "--max-response-bytes", "1000"],
        ["process", "--run-id", "run-1"],
        [
            "process",
            "--run-id",
            "run-1",
            "--retry-failures",
            "--workers",
            "2",
            "--artifacts",
            "artifacts",
            "--json",
        ],
        ["publish", "--run-id", "run-1"],
        [
            "fixture",
            "fill",
            "--fixture",
            "f-1",
            "--run-id",
            "run-1",
            "--target-id",
            "target-1",
            "--attempt-id",
            "attempt-1",
            "--max-response-bytes",
            "1024",
        ],
        ["fixture", "create", "--fixture", "f-1"],
        [
            "fixture",
            "list",
            "--fixture",
            "f-1",
            "--capture-id",
            "cap-1",
            "--target-id",
            "target-1",
        ],
        [
            "fixture",
            "replay",
            "--fixture",
            "f-1",
            "--capture-id",
            "cap-1",
            "--target-id",
            "target-1",
            "--output",
            "response.bin",
        ],
        ["review", "generate", "--fixture", "f-1"],
        ["review", "compare", "--base", "left", "--new", "right"],
        ["snapshot", "audit"],
    ):
        assert parser.parse_args(args)


def test_process_options_preserve_defaults_and_validate_workers() -> None:
    parser = cli.build_parser()
    parsed = parser.parse_args(["process", "--run-id", "run-1"])
    assert parsed.run_id == "run-1"
    assert parsed.workers is None
    assert parsed.artifacts is None
    assert parsed.json is False
    assert parsed.retry_failures is False

    with pytest.raises(SystemExit):
        parser.parse_args(["process", "--run-id", "run-1", "--workers", "0"])


def test_response_ceiling_options_are_optional_but_positive_when_supplied() -> None:
    parsed_run = cli.build_parser().parse_args(["run", "--run-id", "run-1"])
    assert parsed_run.max_response_bytes is None
    assert not parsed_run.retain_response_evidence
    parsed_capture = cli.build_parser().parse_args(
        [
            "fixture",
            "fill",
            "--fixture",
            "f-1",
            "--run-id",
            "run-1",
            "--target-id",
            "target-1",
            "--attempt-id",
            "attempt-1",
        ]
    )
    assert parsed_capture.max_response_bytes is None
    for args in (
        ["run", "--run-id", "run-1", "--max-response-bytes", "0"],
        [
            "fixture",
            "fill",
            "--fixture",
            "f-1",
            "--run-id",
            "run-1",
            "--target-id",
            "target-1",
            "--attempt-id",
            "attempt-1",
            "--max-response-bytes",
            "0",
        ],
    ):
        with pytest.raises(SystemExit):
            cli.build_parser().parse_args(args)


def test_publish_todo_reports_gate_and_does_not_claim_publication(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = cli.main(["publish", "--run-id", "run-1", "--json"])

    assert result == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "blocked_by_gate"
    assert "representative S9/S10 evidence and explicit approval" in payload["message"]


def test_review_generate_and_snapshot_have_separate_handlers(
    tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = []
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.review_adapter.cmd_review_artifacts",
        lambda args: calls.append(args) or 0,
    )
    review_result = cli.main(
        [
            "review",
            "generate",
            "--fixture",
            "fixture-1",
            "--capture-id",
            "capture-1",
            "--target-id",
            "target-1",
            "--output",
            str(tmp_path / "review"),
            "--artifacts",
            str(tmp_path),
            "--json",
        ]
    )
    snapshot_result = cli.main(["snapshot", "status", "--json"])
    snapshot = json.loads(capsys.readouterr().out)

    assert review_result == 0
    assert calls[0].fixture == "fixture-1"
    assert calls[0].capture_id == "capture-1"
    assert calls[0].target_id == "target-1"
    assert calls[0].output == str(tmp_path / "review")
    assert calls[0].json
    assert snapshot_result == 2
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
