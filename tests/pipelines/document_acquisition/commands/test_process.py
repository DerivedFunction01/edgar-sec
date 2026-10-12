from __future__ import annotations

import json
import sys
from types import ModuleType, SimpleNamespace

from edgar_sec.pipelines.document_acquisition import cli
from edgar_sec.pipelines.document_acquisition.commands import process


def _processing_service(monkeypatch, execute) -> None:
    module = ModuleType("edgar_sec.pipelines.document_acquisition.processing_run")
    module.execute_processing_run = execute
    monkeypatch.setitem(
        sys.modules,
        "edgar_sec.pipelines.document_acquisition.processing_run",
        module,
    )


def test_process_wires_service_once_and_emits_json_summary(monkeypatch, capsys) -> None:
    paths = object()
    calls = []
    path_calls = []
    summary = {"success": True, "run_id": "run-1", "processed_count": 3}

    def execute(run_id, received_paths, *, retry_failures, workers):
        calls.append((run_id, received_paths, retry_failures, workers))
        return summary

    _processing_service(monkeypatch, execute)
    monkeypatch.setattr(
        process,
        "resolve_acquisition_paths",
        lambda *, artifacts_root: path_calls.append(artifacts_root) or paths,
    )

    status = cli.main(
        [
            "process",
            "--run-id",
            "run-1",
            "--retry-failures",
            "--workers",
            "4",
            "--artifacts",
            "artifact-root",
            "--json",
        ]
    )

    assert status == 0
    assert path_calls == ["artifact-root"]
    assert calls == [("run-1", paths, True, 4)]
    assert json.loads(capsys.readouterr().out) == summary


def test_process_text_summary_and_failed_report_return_nonzero(monkeypatch, capsys):
    paths = object()
    summary = {"success": False, "run_id": "run-2", "failed_count": 1}
    calls = []
    _processing_service(
        monkeypatch,
        lambda *args, **kwargs: calls.append((args, kwargs)) or summary,
    )
    monkeypatch.setattr(
        process, "resolve_acquisition_paths", lambda *, artifacts_root: paths
    )

    status = cli.main(["process", "--run-id", "run-2"])

    assert status == 1
    assert calls == [
        (
            ("run-2", paths),
            {"retry_failures": False, "workers": None},
        )
    ]
    assert capsys.readouterr().out == ('failed_count=1 run_id="run-2" success=false\n')


def test_process_does_not_initialize_network_transport_or_acquisition_runner(
    monkeypatch, capsys
) -> None:
    calls = []
    _processing_service(
        monkeypatch,
        lambda *args, **kwargs: calls.append((args, kwargs)) or {"success": True},
    )
    monkeypatch.setattr(
        process,
        "resolve_acquisition_paths",
        lambda *, artifacts_root: SimpleNamespace(artifacts_root=artifacts_root),
    )

    def unexpected(*args, **kwargs):
        raise AssertionError("processing must not initialize acquisition transport")

    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.commands.common.sec_transport_factory",
        unexpected,
    )
    monkeypatch.setattr(
        "edgar_sec.pipelines.document_acquisition.runner.execute_acquisition_run",
        unexpected,
    )

    assert cli.main(["process", "--run-id", "run-3", "--json"]) == 0
    assert calls
    assert json.loads(capsys.readouterr().out) == {"success": True}
