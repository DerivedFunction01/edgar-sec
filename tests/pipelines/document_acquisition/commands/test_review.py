from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from edgar_sec.pipelines.document_acquisition.commands import review


def test_review_generate_uses_configured_root_and_emits_json(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    paths = object()
    received = {}
    monkeypatch.setattr(
        review,
        "resolve_acquisition_paths",
        lambda *, artifacts_root: (
            received.setdefault("artifacts_root", artifacts_root) or paths
        ),
    )
    monkeypatch.setattr(
        review,
        "build_review_artifacts",
        lambda *args, **kwargs: SimpleNamespace(
            review_id="run-1",
            output_root=tmp_path / "run-1",
            summary=SimpleNamespace(
                total=1, completed=1, replay_failure=0, execution_error=0
            ),
            exit_code=0,
        ),
    )
    args = SimpleNamespace(
        fixture="fixture-1",
        output=str(tmp_path / "run-1"),
        capture_id="capture-1",
        target_id="target-1",
        accessions=None,
        limit=None,
        workers=None,
        artifacts_root="",
        json=True,
    )

    assert review.cmd_review_artifacts(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert received["artifacts_root"] is None
    assert result["command"] == "review generate"
    assert result["fixture_id"] == "fixture-1"
    assert result["completed"] == 1
