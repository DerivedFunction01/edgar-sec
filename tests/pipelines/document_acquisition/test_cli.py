from __future__ import annotations

import json
from contextlib import contextmanager
from hashlib import sha256
from types import SimpleNamespace
from pathlib import Path

import pytest

from edgar_sec.pipelines.document_acquisition import cli, operator
from edgar_sec.pipelines.document_acquisition.models import (
    AcquisitionStatusReport,
    RunLockInfo,
)
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths


def test_parser_registers_independent_acquisition_tracks() -> None:
    parser = cli.build_parser()

    for args in (
        ["project", "--plan-id", "plan-1"],
        ["status"],
        ["run", "--run-id", "run-1", "--max-response-bytes", "1000"],
        ["process", "--run-id", "run-1"],
        ["publish", "--run-id", "run-1"],
        ["fixture", "capture", "--fixture-id", "f-1", "--run-id", "run-1"],
        ["review", "build", "--run-id", "run-1"],
        ["snapshot", "audit"],
    ):
        assert parser.parse_args(args)


def test_run_requires_a_finite_response_ceiling() -> None:
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["run", "--run-id", "run-1"])

    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(
            ["run", "--run-id", "run-1", "--max-response-bytes", "0"]
        )


def test_run_command_delegates_policy_and_keeps_transport_lazy(
    capsys: pytest.CaptureFixture[str], tmp_path, monkeypatch
) -> None:
    calls = []

    def fake_run(run_id, **kwargs):
        calls.append((run_id, kwargs))
        return SimpleNamespace(
            run_id=run_id,
            state="complete",
            target_counts={"acquired": 2, "pending": 0},
            attempted_count=2,
            retryable_failure_count=0,
            non_retryable_failure_count=0,
            cancelled=False,
        )

    monkeypatch.setattr(cli, "execute_acquisition_run", fake_run)
    result = cli.main(
        [
            "run",
            "--run-id",
            "run-1",
            "--max-response-bytes",
            "2048",
            "--workers",
            "4",
            "--artifacts",
            str(tmp_path),
            "--json",
        ]
    )

    assert result == 0
    run_id, arguments = calls[0]
    assert run_id == "run-1"
    assert arguments["policy"].max_response_bytes == 2048
    assert arguments["policy"].requested_workers == 4
    assert arguments["transport"]._http_client is None
    assert arguments["transport"]._broker is None
    assert json.loads(capsys.readouterr().out)["state"] == "complete"


def test_lazy_cli_transport_streams_through_shared_broker(
    tmp_path, monkeypatch
) -> None:
    from edgar_sec.infra.broker.sec_broker import StreamedFileResult

    class FakeHttpClient:
        closed = False

        def close(self):
            self.closed = True

    class FakeBrokerClient:
        closed = False
        request = None

        def stream_to_file(
            self,
            url,
            *,
            max_response_bytes,
            accession_cik,
            accession_number,
            staging_root,
        ):
            self.request = (url, max_response_bytes, accession_cik, accession_number)
            body = b"broker-streamed"
            path = Path(staging_root) / "sec-stream-test.part"
            path.write_bytes(body)
            return StreamedFileResult(
                "ok",
                path,
                sha256(body).hexdigest(),
                len(body),
                url,
                url,
                200,
                "text/html",
                None,
                None,
                None,
            )

        def close(self):
            self.closed = True

    fake_http = FakeHttpClient()
    fake_broker = FakeBrokerClient()
    exited = []

    @contextmanager
    def fake_managed_broker(socket_path, *, http_client):
        assert http_client is fake_http
        yield fake_broker
        exited.append(socket_path)

    monkeypatch.setattr(cli, "managed_broker", fake_managed_broker)
    staging = tmp_path / "staging"
    staging.mkdir(parents=True)
    destination = staging / "response-generated.bin"
    url = "https://www.sec.gov/Archives/edgar/data/320193/000032019320000096/report.htm"
    validated = []
    transport = cli._LazySecTransport(lambda: fake_http)

    response = transport.stream_to_file(
        url,
        destination,
        max_response_bytes=256,
        validate_redirect=validated.append,
    )
    transport.close()

    assert response.path == destination
    assert destination.read_bytes() == b"broker-streamed"
    assert fake_broker.request == (url, 256, "320193", "000032019320000096")
    assert validated == [url]
    assert fake_broker.closed and fake_http.closed and exited


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


def test_status_lists_validated_runs_in_sorted_order(
    capsys: pytest.CaptureFixture[str], tmp_path, monkeypatch
) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    paths.run_dir("run-b").mkdir(parents=True)
    paths.run_dir("run-a").mkdir(parents=True)
    validated = []

    def fake_load(_paths, run_id):
        validated.append(run_id)
        return ()

    def fake_inspect(run_id, *, database_path, lock_path):
        return AcquisitionStatusReport(
            run_id=run_id,
            state="ready",
            target_counts={"pending": 1, "acquired": 0},
            retryable_failure_count=0,
            non_retryable_failure_count=0,
            active_lock=None,
            invalid_reason=None,
        )

    monkeypatch.setattr(cli, "load_validated_work_order", fake_load)
    monkeypatch.setattr(cli, "inspect_run_state", fake_inspect)

    result = cli.main(["status", "--artifacts", str(tmp_path), "--json"])

    assert result == 0
    assert validated == ["run-a", "run-b"]
    assert [run["run_id"] for run in json.loads(capsys.readouterr().out)["runs"]] == [
        "run-a",
        "run-b",
    ]


def test_status_marks_invalid_work_orders(capsys, tmp_path, monkeypatch) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    paths.run_dir("run-1").mkdir(parents=True)
    monkeypatch.setattr(
        cli,
        "load_validated_work_order",
        lambda _paths, _run_id: (_ for _ in ()).throw(ValueError("bad manifest")),
    )
    monkeypatch.setattr(
        cli,
        "inspect_run_state",
        lambda run_id, **kwargs: AcquisitionStatusReport(
            run_id=run_id,
            state="ready",
            target_counts={"pending": 1},
            retryable_failure_count=0,
            non_retryable_failure_count=0,
            active_lock=None,
            invalid_reason=None,
        ),
    )

    result = cli.main(
        ["status", "--run-id", "run-1", "--artifacts", str(tmp_path), "--json"]
    )

    assert result == 1
    report = json.loads(capsys.readouterr().out)["runs"][0]
    assert report["state"] == "invalid"
    assert report["invalid_reason"] == "bad manifest"


def test_status_does_not_expose_run_lock_owner_token(
    capsys: pytest.CaptureFixture[str], tmp_path, monkeypatch
) -> None:
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    paths.run_dir("run-1").mkdir(parents=True)
    monkeypatch.setattr(cli, "load_validated_work_order", lambda _paths, _run_id: ())
    monkeypatch.setattr(
        cli,
        "inspect_run_state",
        lambda run_id, **kwargs: AcquisitionStatusReport(
            run_id=run_id,
            state="running",
            target_counts={"pending": 1},
            retryable_failure_count=0,
            non_retryable_failure_count=0,
            active_lock=RunLockInfo(
                "host", 100, "2025-01-01T00:00:00Z", "private-token"
            ),
            invalid_reason=None,
        ),
    )

    cli.main(["status", "--run-id", "run-1", "--artifacts", str(tmp_path), "--json"])

    output = capsys.readouterr().out
    assert "private-token" not in output
    assert '"pid": 100' in output


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
