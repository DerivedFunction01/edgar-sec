from __future__ import annotations

import json

import pytest

from edgar_sec.pipelines.document_acquisition import cli, operator


def test_parser_registers_acquisition_tracks() -> None:
    parser = cli.build_parser()

    for args in (
        ["project", "--plan-id", "plan-1"],
        ["status"],
        ["status", "--run-id", "run-1", "--target-id", "target-1"],
        ["run", "--run-id", "run-1", "--max-response-bytes", "1000"],
        ["publish", "--run-id", "run-1"],
        [
            "fixture",
            "fill",
            "--fixture",
            "f-1",
            "--plan-id",
            "plan-1",
            "--allow-network",
        ],
        ["fixture", "create", "--fixture", "f-1", "--plan-id", "plan-1"],
        [
            "fixture",
            "list",
            "--fixture",
            "f-1",
        ],
        ["review", "generate", "--fixture", "f-1"],
        ["review", "compare", "--base", "left", "--new", "right"],
        ["review", "analyze", "--run", "review-run"],
        ["review", "holdout", "--run", "review-run", "--spec", "holdout.json"],
        [
            "review",
            "label",
            "--artifact",
            "review/cases/case-a/processing-review.json",
            "--outcome",
            "positive",
            "--observed-kind",
            "exhibit",
            "--observed-authority",
            "reg_s_k_item_601",
            "--observed-code",
            "3.1",
            "--annotator-id",
            "reviewer-a",
            "--annotated-at-utc",
            "2026-10-13T20:00:00Z",
            "--evidence-ref",
            "text:0-40",
        ],
    ):
        assert parser.parse_args(args)

    with pytest.raises(SystemExit):
        parser.parse_args(["snapshot", "audit"])
        parser.parse_args(["review", "audit"])
    with pytest.raises(SystemExit):
        parser.parse_args(["fixture", "replay", "--fixture", "f-1"])


def test_process_is_not_a_cli_alias_and_run_owns_retry_options() -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["process", "--run-id", "run-1"])

    parsed = parser.parse_args(
        ["run", "--run-id", "run-1", "--retry-failures", "--workers", "2"]
    )
    assert parsed.run_id == "run-1"
    assert parsed.workers == 2
    assert parsed.retry_failures is True
    with pytest.raises(SystemExit):
        parser.parse_args(["run", "--run-id", "run-1", "--workers", "0"])


def test_run_response_ceiling_is_optional_but_positive_when_supplied() -> None:
    parsed_run = cli.build_parser().parse_args(["run", "--run-id", "run-1"])
    assert parsed_run.max_response_bytes is None
    assert not parsed_run.retain_response_evidence
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(
            ["run", "--run-id", "run-1", "--max-response-bytes", "0"]
        )


def test_fixture_commands_reject_manual_hash_filters() -> None:
    parser = cli.build_parser()
    for args in (
        [
            "fixture",
            "fill",
            "--fixture",
            "f-1",
            "--run-id",
            "run-1",
            "--target-id",
            "t-1",
        ],
        [
            "fixture",
            "fill",
            "--fixture",
            "f-1",
            "--run-id",
            "run-1",
            "--attempt-id",
            "a-1",
        ],
        ["fixture", "list", "--capture-id", "c-1"],
        ["review", "generate", "--fixture", "f-1", "--target-id", "t-1"],
        ["review", "generate", "--fixture", "f-1", "--capture-id", "c-1"],
    ):
        with pytest.raises(SystemExit):
            parser.parse_args(args)


def test_publish_cli_reports_missing_manifest_when_run_does_not_exist(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = cli.main(["publish", "--run-id", "run-1", "--json"])

    assert result == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "publish"
    assert payload["status"] == "error"
    assert "run manifest is missing" in payload["error"]


def test_review_analyze_dispatches_offline_runs(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(cli, "cmd_review_analyze", lambda args: calls.append(args) or 0)

    result = cli.main(
        ["review", "analyze", "--run", "run-a", "--run", "run-b", "--json"]
    )

    assert result == 0
    assert calls[0].run == ["run-a", "run-b"]


def test_review_generate_and_snapshot_have_separate_handlers(
    tmp_path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = []
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.cli.cmd_review_artifacts",
        lambda args: calls.append(args) or 0,
    )
    review_result = cli.main(
        [
            "review",
            "generate",
            "--fixture",
            "fixture-1",
            "--output",
            str(tmp_path / "review"),
            "--artifacts",
            str(tmp_path),
            "--json",
        ]
    )
    snapshot_result = cli.main(
        ["snapshot", "status", "--artifacts", str(tmp_path), "--json"]
    )
    snapshot = json.loads(capsys.readouterr().out)

    assert review_result == 0
    assert calls[0].fixture == "fixture-1"
    assert calls[0].output == str(tmp_path / "review")
    assert calls[0].json
    assert snapshot_result == 0
    assert snapshot["command"] == "snapshot status"
    assert snapshot["published"] is False
    assert snapshot["snapshot_id"] is None


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


def test_cmd_run_forwards_progress_callback(monkeypatch) -> None:
    """Verify cmd_run invokes execute_acquisition_run with progress callback parameter."""
    from edgar_sec.pipelines.document_acquisition.commands.run import cmd_run
    from edgar_sec.pipelines.document_acquisition.models import AcquisitionRunReport

    calls = []
    dummy = AcquisitionRunReport(
        run_id="run-1",
        state="complete",
        target_counts={},
        attempted_count=0,
        retryable_failure_count=0,
        non_retryable_failure_count=0,
        cancelled=False,
        processing_operation_counts={},
        processing_attempted_target_count=0,
        processing_complete=True,
        processing_success=True,
    )
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.commands.run.execute_acquisition_run",
        lambda *args, **kwargs: calls.append(kwargs) or dummy,
    )
    parser = cli.build_parser()
    args = parser.parse_args(["run", "--run-id", "run-1", "--json"])
    assert cmd_run(args) == 0
    assert "progress_callback" in calls[0]
