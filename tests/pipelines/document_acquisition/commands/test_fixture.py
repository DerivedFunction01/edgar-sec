from __future__ import annotations

import json

from edgar_sec.pipelines.document_acquisition import cli
from edgar_sec.pipelines.document_acquisition.commands import common, fixture
from edgar_sec.pipelines.document_acquisition.fixture_operator import (
    FixtureCaptureResult,
    FixtureReplayResult,
)
from edgar_sec.pipelines.document_acquisition.commands import run


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
            "--fixture-id",
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


def test_fixture_capture_delegates_all_identifiers_and_policy(
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
            "capture",
            "--fixture-id",
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
        "command": "fixture capture",
        "fixture_id": "fixture-1",
        "response_sha256": None,
        "reused_response": False,
        "run_id": "run-1",
        "source_byte_size": None,
        "status": "captured",
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
            "capture",
            "--fixture-id",
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
            "--fixture-id",
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
            "--fixture-id",
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
    assert cli.main(["fixture", "create", "--fixture-id", "bad", "--json"]) == 1
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
