from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from edgar_sec.infra.sec_http.streaming import StreamFailure, StreamedResponse
from edgar_sec.pipelines.document_acquisition import cli
from edgar_sec.pipelines.document_acquisition.commands import common, fixture
from edgar_sec.pipelines.document_acquisition.commands import run
from edgar_sec.pipelines.document_acquisition.fixture_store.capture import (
    FixtureCaptureResult,
)
from edgar_sec.pipelines.document_acquisition.fixture_store.reader import (
    FixtureReplayResult,
)
from edgar_sec.pipelines.document_acquisition.models import AcquisitionPolicy
from edgar_sec.pipelines.document_acquisition.run_state.store import get_target_state
from edgar_sec.pipelines.document_acquisition.runner import execute_acquisition_run
from tests.support import make_acquisition_run


class _FixtureCliTransport:
    def __init__(self, responses, *, failures=None):
        self.responses = responses
        self.failures = failures or {}

    def stream_to_file(
        self,
        url,
        destination,
        *,
        max_response_bytes,
        validate_redirect,
    ):
        validate_redirect(url)
        if url in self.failures:
            return self.failures[url]
        body = self.responses[url]
        if len(body) > max_response_bytes:
            raise AssertionError("synthetic response exceeded its byte budget")
        path = Path(destination)
        path.write_bytes(body)
        return StreamedResponse(
            status_code=200,
            requested_url=url,
            final_url=url,
            sha256=hashlib.sha256(body).hexdigest(),
            byte_size=len(body),
            content_type="text/html",
            content_encoding=None,
            path=path,
        )

    def close(self):
        pass


def _execute_run(
    paths, run_id, responses, monkeypatch, *, failures=None, retry_failures=False
):
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.runner.derive_resources",
        lambda: SimpleNamespace(workers=1, worker_ceiling=1),
    )
    return execute_acquisition_run(
        run_id,
        retry_failures=retry_failures,
        paths=paths,
        policy=AcquisitionPolicy(
            max_response_bytes=4096,
            retain_response_evidence=True,
        ),
        transport=_FixtureCliTransport(responses, failures=failures),
        clock=lambda: datetime(2025, 1, 1, tzinfo=UTC),
    )


def test_fixture_create_delegates_and_emits_stable_json(capsys, tmp_path, monkeypatch):
    calls = []
    fixture_root = tmp_path / "fixtures" / "fixture-1"
    monkeypatch.setattr(
        fixture,
        "create_fixture",
        lambda fixture_id, *, paths: (
            calls.append((fixture_id, paths.artifacts_root)) or fixture_root
        ),
    )

    result = cli.main(
        [
            "fixture",
            "create",
            "--fixture",
            "fixture-1",
            "--artifacts",
            str(tmp_path),
            "--json",
        ]
    )

    assert result == 0
    assert calls == [("fixture-1", tmp_path.resolve())]
    assert json.loads(capsys.readouterr().out) == {
        "command": "fixture create",
        "fixture_id": "fixture-1",
        "path": str(fixture_root),
        "status": "created",
    }


def test_fixture_fill_delegates_all_identifiers_and_policy(
    capsys, tmp_path, monkeypatch
) -> None:
    calls = []

    def fake_capture(
        fixture_id, run_id, target_id, attempt_id, *, paths, max_response_bytes
    ):
        calls.append(
            (
                fixture_id,
                run_id,
                target_id,
                attempt_id,
                paths.artifacts_root,
                max_response_bytes,
            )
        )
        return FixtureCaptureResult(
            fixture_id,
            "cap-1",
            run_id,
            target_id,
            attempt_id,
            "failed",
            None,
            None,
            False,
        )

    monkeypatch.setattr(fixture, "capture_fixture_case", fake_capture)
    result = cli.main(
        [
            "fixture",
            "fill",
            "--fixture",
            "fixture-1",
            "--run-id",
            "run-1",
            "--target-id",
            "target-1",
            "--attempt-id",
            "attempt-1",
            "--max-response-bytes",
            "2048",
            "--artifacts",
            str(tmp_path),
            "--json",
        ]
    )

    assert result == 0
    assert calls == [
        ("fixture-1", "run-1", "target-1", "attempt-1", tmp_path.resolve(), 2048)
    ]
    assert json.loads(capsys.readouterr().out) == {
        "attempt_id": "attempt-1",
        "acquisition_status": "failed",
        "capture_id": "cap-1",
        "command": "fixture fill",
        "fixture_id": "fixture-1",
        "response_sha256": None,
        "reused_response": False,
        "run_id": "run-1",
        "source_byte_size": None,
        "status": "filled",
        "target_id": "target-1",
    }


def test_fixture_capture_uses_configured_response_limit_when_omitted(
    tmp_path, monkeypatch
) -> None:
    calls = []
    monkeypatch.setattr(
        common,
        "resolve_settings",
        lambda *, include: {"acquisition.max_response_bytes": 268435456},
    )
    monkeypatch.setattr(
        fixture,
        "capture_fixture_case",
        lambda *args, **kwargs: (
            calls.append(kwargs["max_response_bytes"])
            or FixtureCaptureResult(
                args[0], "cap-1", args[1], args[2], args[3], "failed", None, None, False
            )
        ),
    )

    result = cli.main(
        [
            "fixture",
            "fill",
            "--fixture",
            "fixture-1",
            "--run-id",
            "run-1",
            "--target-id",
            "target-1",
            "--attempt-id",
            "attempt-1",
            "--artifacts",
            str(tmp_path),
        ]
    )

    assert result == 0
    assert calls == [268435456]


def test_fixture_list_uses_streaming_discovery_and_filters(
    capsys, tmp_path, monkeypatch
) -> None:
    calls = []

    def fixture_ids(_paths):
        yield "fixture-1"
        yield "fixture-2"

    def fixture_cases(paths, *, fixture_id, capture_id, target_id):
        calls.append((paths.artifacts_root, fixture_id, capture_id, target_id))
        return iter(())

    monkeypatch.setattr(fixture, "list_fixtures", fixture_ids)
    monkeypatch.setattr(fixture, "list_fixture_cases", fixture_cases)

    result = cli.main(
        [
            "fixture",
            "list",
            "--fixture",
            "fixture-2",
            "--capture-id",
            "cap-1",
            "--target-id",
            "target-1",
            "--artifacts",
            str(tmp_path),
            "--json",
        ]
    )

    assert result == 0
    assert calls == [(tmp_path.resolve(), "fixture-2", "cap-1", "target-1")]
    assert json.loads(capsys.readouterr().out) == {
        "cases": [],
        "command": "fixture list",
        "fixtures": ["fixture-2"],
        "status": "ok",
    }


def test_fixture_replay_is_local_and_returns_metadata_only_case(
    capsys, tmp_path, monkeypatch
) -> None:
    calls = []

    def fake_replay(fixture_id, capture_id, target_id, output_path, *, paths):
        calls.append(
            (fixture_id, capture_id, target_id, output_path, paths.artifacts_root)
        )
        return FixtureReplayResult(
            fixture_id,
            capture_id,
            target_id,
            "attempt-1",
            "failed",
            None,
            None,
            None,
            None,
        )

    def unexpected(*_args, **_kwargs):
        raise AssertionError("fixture replay must not start acquisition transport")

    monkeypatch.setattr(fixture, "replay_fixture_case", fake_replay)
    monkeypatch.setattr(run, "_LazySecTransport", unexpected)
    monkeypatch.setattr(run, "execute_acquisition_run", unexpected)
    output = tmp_path / "response.bin"

    result = cli.main(
        [
            "fixture",
            "replay",
            "--fixture",
            "fixture-1",
            "--capture-id",
            "cap-1",
            "--target-id",
            "target-1",
            "--output",
            str(output),
            "--artifacts",
            str(tmp_path),
            "--json",
        ]
    )

    assert result == 0
    assert calls == [("fixture-1", "cap-1", "target-1", output, tmp_path.resolve())]
    assert json.loads(capsys.readouterr().out) == {
        "acquisition_status": "failed",
        "attempt_id": "attempt-1",
        "capture_id": "cap-1",
        "command": "fixture replay",
        "fixture_id": "fixture-1",
        "output_path": None,
        "response_sha256": None,
        "selected_byte_size": None,
        "selected_sha256": None,
        "status": "metadata_only",
        "target_id": "target-1",
    }


def test_fixture_errors_are_stable_and_json_list_is_atomic(
    capsys, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        fixture,
        "create_fixture",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("invalid path")),
    )
    assert cli.main(["fixture", "create", "--fixture", "bad", "--json"]) == 1
    assert json.loads(capsys.readouterr().out) == {
        "command": "fixture create",
        "error": "invalid path",
        "status": "error",
    }

    def broken_cases(*_args, **_kwargs):
        yield from ()
        raise ValueError("corrupt fixture metadata")

    monkeypatch.setattr(fixture, "list_fixtures", lambda _paths: iter(("fixture-1",)))
    monkeypatch.setattr(fixture, "list_fixture_cases", broken_cases)
    assert cli.main(["fixture", "list", "--artifacts", str(tmp_path), "--json"]) == 1
    assert json.loads(capsys.readouterr().out) == {
        "command": "fixture list",
        "error": "corrupt fixture metadata",
        "status": "error",
    }


def test_bundle_response_fixture_cli_round_trip_preserves_response_and_child(
    tmp_path, monkeypatch, capsys
) -> None:
    paths, run_id, row = make_acquisition_run(tmp_path, lazy=False, bundle=True)
    selected = b"selected report bytes\r\n"
    envelope = (
        b"<DOCUMENT><SEQUENCE>1<TEXT>other child</TEXT></DOCUMENT>"
        b"<DOCUMENT><SEQUENCE>2<FILENAME>report.htm<TYPE>10-K<TEXT>"
        + selected
        + b"</TEXT></DOCUMENT>"
    )
    report = _execute_run(paths, run_id, {row["target_url"]: envelope}, monkeypatch)
    assert report.target_counts["acquired"] == 1
    state = get_target_state(paths.run_state_path(run_id), "target-1")
    assert state is not None and state.last_attempt_id is not None
    artifacts = str(paths.artifacts_root)

    assert (
        cli.main(
            [
                "fixture",
                "create",
                "--fixture",
                "bundle-cli",
                "--artifacts",
                artifacts,
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        cli.main(
            [
                "fixture",
                "fill",
                "--fixture",
                "bundle-cli",
                "--run-id",
                run_id,
                "--target-id",
                "target-1",
                "--attempt-id",
                state.last_attempt_id,
                "--artifacts",
                artifacts,
                "--json",
            ]
        )
        == 0
    )
    capture = json.loads(capsys.readouterr().out)
    assert capture["attempt_id"] == state.last_attempt_id

    assert (
        cli.main(
            [
                "fixture",
                "list",
                "--fixture",
                "bundle-cli",
                "--artifacts",
                artifacts,
                "--json",
            ]
        )
        == 0
    )
    case = json.loads(capsys.readouterr().out)["cases"][0]
    envelope_digest = hashlib.sha256(envelope).hexdigest()
    selected_digest = hashlib.sha256(selected).hexdigest()
    assert case["capture_id"] == capture["capture_id"]
    assert case["attempt_id"] == state.last_attempt_id
    assert case["response_sha256"] == envelope_digest
    assert case["selected_sha256"] == selected_digest
    assert case["sequence"] == 2
    assert case["selected_filename"] == "report.htm"
    with sqlite3.connect(paths.fixture_database_path("bundle-cli")) as connection:
        stored_digests = {
            value[0]
            for value in connection.execute(
                "SELECT response_sha256 FROM response_bodies"
            )
        }
    assert stored_digests == {envelope_digest}

    output = tmp_path / "bundle-child.bin"
    assert (
        cli.main(
            [
                "fixture",
                "replay",
                "--fixture",
                "bundle-cli",
                "--capture-id",
                capture["capture_id"],
                "--target-id",
                "target-1",
                "--output",
                str(output),
                "--artifacts",
                artifacts,
                "--json",
            ]
        )
        == 0
    )
    replay = json.loads(capsys.readouterr().out)
    assert replay["selected_sha256"] == selected_digest
    assert output.read_bytes() == selected


def test_fixture_cli_captures_current_successful_retry_attempt(
    tmp_path, monkeypatch, capsys
) -> None:
    paths, run_id, row = make_acquisition_run(tmp_path, lazy=False)
    failure = StreamFailure("transport_error", True, None, "temporary failure")
    _execute_run(paths, run_id, {}, monkeypatch, failures={row["target_url"]: failure})
    first_state = get_target_state(paths.run_state_path(run_id), "target-1")
    assert first_state is not None and first_state.last_attempt_id is not None
    first_attempt_id = first_state.last_attempt_id

    body = b"successful retry response"
    report = _execute_run(
        paths,
        run_id,
        {row["target_url"]: body},
        monkeypatch,
        retry_failures=True,
    )
    assert report.target_counts["acquired"] == 1
    state = get_target_state(paths.run_state_path(run_id), "target-1")
    assert state is not None and state.last_attempt_id is not None
    assert state.last_attempt_id != first_attempt_id
    artifacts = str(paths.artifacts_root)

    assert (
        cli.main(
            [
                "fixture",
                "create",
                "--fixture",
                "retry-cli",
                "--artifacts",
                artifacts,
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        cli.main(
            [
                "fixture",
                "fill",
                "--fixture",
                "retry-cli",
                "--run-id",
                run_id,
                "--target-id",
                "target-1",
                "--attempt-id",
                state.last_attempt_id,
                "--artifacts",
                artifacts,
                "--json",
            ]
        )
        == 0
    )
    captured = json.loads(capsys.readouterr().out)
    assert captured["attempt_id"] == state.last_attempt_id
    assert captured["acquisition_status"] == "acquired"
    assert captured["response_sha256"] == hashlib.sha256(body).hexdigest()

    assert (
        cli.main(
            [
                "fixture",
                "list",
                "--fixture",
                "retry-cli",
                "--artifacts",
                artifacts,
                "--json",
            ]
        )
        == 0
    )
    case = json.loads(capsys.readouterr().out)["cases"][0]
    assert case["attempt_id"] == state.last_attempt_id
    assert case["attempt_id"] != first_attempt_id
