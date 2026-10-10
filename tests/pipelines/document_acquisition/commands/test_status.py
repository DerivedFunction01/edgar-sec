from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from edgar_sec.pipelines.document_acquisition import cli
from edgar_sec.pipelines.document_acquisition.commands import status
from edgar_sec.pipelines.document_acquisition.models import (
    AcquisitionAttempt,
    AcquisitionStatusReport,
    RunLockInfo,
)
from edgar_sec.pipelines.document_acquisition.paths import resolve_acquisition_paths


def test_status_lists_validated_runs_in_sorted_order(capsys, tmp_path, monkeypatch):
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    paths.run_dir("run-b").mkdir(parents=True)
    paths.run_dir("run-a").mkdir(parents=True)
    validated = []

    def fake_load(_paths, run_id):
        validated.append(run_id)
        return ()

    def fake_inspect(run_id, **_):
        return AcquisitionStatusReport(
            run_id, "ready", {"pending": 1}, 0, 0, None, None
        )

    monkeypatch.setattr(status, "load_validated_work_order", fake_load)
    monkeypatch.setattr(status, "inspect_run_state", fake_inspect)

    result = cli.main(["status", "--artifacts", str(tmp_path), "--json"])

    assert result == 0
    assert validated == ["run-a", "run-b"]
    assert [row["run_id"] for row in json.loads(capsys.readouterr().out)["runs"]] == [
        "run-a",
        "run-b",
    ]


def test_status_marks_invalid_work_orders(capsys, tmp_path, monkeypatch):
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    paths.run_dir("run-1").mkdir(parents=True)
    monkeypatch.setattr(
        status,
        "load_validated_work_order",
        lambda *_: (_ for _ in ()).throw(ValueError("bad manifest")),
    )
    monkeypatch.setattr(
        status,
        "inspect_run_state",
        lambda run_id, **_: AcquisitionStatusReport(
            run_id, "ready", {"pending": 1}, 0, 0, None, None
        ),
    )

    result = cli.main(
        ["status", "--run-id", "run-1", "--artifacts", str(tmp_path), "--json"]
    )

    assert result == 1
    row = json.loads(capsys.readouterr().out)["runs"][0]
    assert row["state"] == "invalid"
    assert row["invalid_reason"] == "bad manifest"


def test_status_does_not_expose_run_lock_owner_token(capsys, tmp_path, monkeypatch):
    paths = resolve_acquisition_paths(artifacts_root=tmp_path)
    paths.run_dir("run-1").mkdir(parents=True)
    monkeypatch.setattr(status, "load_validated_work_order", lambda *_: ())
    monkeypatch.setattr(
        status,
        "inspect_run_state",
        lambda run_id, **_: AcquisitionStatusReport(
            run_id,
            "running",
            {"pending": 1},
            0,
            0,
            RunLockInfo("host", 100, "2025-01-01T00:00:00Z", "private-token"),
            None,
        ),
    )

    cli.main(["status", "--run-id", "run-1", "--artifacts", str(tmp_path), "--json"])

    output = capsys.readouterr().out
    assert "private-token" not in output
    assert '"pid": 100' in output


def test_status_target_view_is_exact_and_stable(capsys, tmp_path, monkeypatch):
    target_id = "target-0123456789abcdef"
    attempt_id = "attempt-0123456789abcdef0123456789abcdef"
    target = SimpleNamespace(target_id=target_id, outcome="failed", attempt_count=1)
    attempt = AcquisitionAttempt(
        attempt_id,
        target_id,
        1,
        "document_body",
        "live_sec",
        "https://www.sec.gov/Archives/request.htm",
        "failed",
        True,
        "transport_error",
        503,
        "https://www.sec.gov/Archives/final.htm",
        "2025-01-01T00:00:00Z",
        "2025-01-01T00:00:01Z",
        "a" * 64,
        123,
        "private/body.bin",
        None,
        None,
        None,
    )
    second = replace(
        attempt, attempt_id="attempt-abcdef0123456789abcdef0123456789", attempt_number=2
    )
    events = []
    monkeypatch.setattr(
        status, "load_validated_work_order", lambda *_: events.append("manifest") or ()
    )
    monkeypatch.setattr(
        status,
        "inspect_run_state",
        lambda run_id, **_: (
            events.append("status")
            or AcquisitionStatusReport(run_id, "ready", {}, 0, 0, None, None)
        ),
    )
    monkeypatch.setattr(
        status, "get_target_state", lambda *_: events.append("target") or target
    )
    monkeypatch.setattr(
        status,
        "list_target_attempts",
        lambda _path, tid: events.append(("attempts", tid)) or [attempt, second],
    )

    for json_output in (True, False):
        args = [
            "status",
            "--run-id",
            "run-1",
            "--target-id",
            target_id,
            "--artifacts",
            str(tmp_path),
        ]
        if json_output:
            args.append("--json")
        assert cli.main(args) == 0
        output = capsys.readouterr().out
        assert attempt_id in output and second.attempt_id in output
        assert "private/body.bin" not in output
        if json_output:
            rows = json.loads(output)["attempts"]
            assert [row["attempt_id"] for row in rows] == [
                attempt_id,
                second.attempt_id,
            ]
            assert rows[0]["requested_url"].endswith("request.htm")
            assert rows[0]["source_sha256"] == "a" * 64
        else:
            assert '"attempt_number": 1' in output
            assert '"attempt_kind": "document_body"' in output
            assert '"error_code": "transport_error"' in output
            assert '"started_at_utc": "2025-01-01T00:00:00Z"' in output
    assert events == ["manifest", "status", "target", ("attempts", target_id)] * 2


def test_status_target_requires_run_and_rejects_unknown(capsys, tmp_path, monkeypatch):
    assert cli.main(["status", "--target-id", "target-1", "--json"]) == 1
    assert (
        json.loads(capsys.readouterr().out)["error"] == "--target-id requires --run-id"
    )
    monkeypatch.setattr(status, "load_validated_work_order", lambda *_: ())
    monkeypatch.setattr(
        status,
        "inspect_run_state",
        lambda rid, **_: AcquisitionStatusReport(rid, "ready", {}, 0, 0, None, None),
    )
    calls = []
    monkeypatch.setattr(status, "get_target_state", lambda *_: calls.append(1) or None)
    monkeypatch.setattr(
        status, "list_target_attempts", lambda *_: pytest.fail("listed unknown target")
    )

    assert (
        cli.main(
            [
                "status",
                "--run-id",
                "run-1",
                "--target-id",
                "missing",
                "--artifacts",
                str(tmp_path),
                "--json",
            ]
        )
        == 1
    )
    assert calls == [1]
    assert json.loads(capsys.readouterr().out)["error"] == "unknown target 'missing'"
