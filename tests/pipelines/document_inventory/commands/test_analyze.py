from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from edgar_sec.pipelines.document_inventory.commands import analyze


def test_review_analyze_emits_json_and_writes_report(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    report = {
        "runs": [
            {"run_id": "run-a", "case_count": 3, "entry_count": 8, "findings": {"x": 2}}
        ],
        "finding_counts": {"x": 2},
    }
    received = []
    monkeypatch.setattr(
        analyze,
        "analyze_review_runs",
        lambda paths, *, artifacts_root, accessions: (
            received.append((paths, artifacts_root, accessions)) or report
        ),
    )
    args = SimpleNamespace(
        artifacts_root=str(tmp_path),
        run_ids=["run-a"],
        accessions=["0000004977-11-000045"],
        output=str(tmp_path / "analysis"),
        json=True,
    )

    assert analyze.cmd_review_analyze(args) == 0

    assert (
        received[0][0][0] == tmp_path / "document_inventory" / "review-runs" / "run-a"
    )
    assert received[0][1] == tmp_path
    assert received[0][2] == {"0000004977-11-000045"}
    assert json.loads(capsys.readouterr().out) == report
    assert json.loads((tmp_path / "analysis" / "analysis.json").read_text()) == report
