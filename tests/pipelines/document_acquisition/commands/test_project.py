from __future__ import annotations

import json
from types import SimpleNamespace

from edgar_sec.pipelines.document_acquisition import cli
from edgar_sec.pipelines.document_acquisition.commands import project


def test_project_command_delegates_to_offline_service(
    capsys, tmp_path, monkeypatch
) -> None:
    calls = []
    manifest = {"target_plan_id": "dplan-1", "target_plan_digest": "a" * 64}

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

    monkeypatch.setattr(project, "project_acquisition_run", fake_project)
    result = cli.main(
        ["project", "--plan-id", "dplan-1", "--artifacts", str(tmp_path), "--json"]
    )

    assert result == 0
    assert calls == [("dplan-1", tmp_path.resolve())]
    assert json.loads(capsys.readouterr().out) == {
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
