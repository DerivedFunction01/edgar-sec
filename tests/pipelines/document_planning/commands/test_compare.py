from __future__ import annotations

import argparse
import json

from edgar_sec.pipelines.document_planning.commands import compare as command


def test_compare_writes_review_artifact_and_manifest(tmp_path, monkeypatch) -> None:
    report = {"schema_version": 1, "target_diff_counts": {"added": 0}}
    monkeypatch.setattr(command, "compare_target_plans", lambda *_args: report)
    output = tmp_path / "review"
    args = argparse.Namespace(
        artifacts=str(tmp_path / "artifacts"),
        base_plan_id="base",
        new_plan_id="new",
        base_profile_id=None,
        new_profile_id=None,
        output=str(output),
        output_id=None,
        json=False,
    )

    assert command.cmd_compare(args) == 0
    artifact = json.loads((output / "target-plan-diff.json").read_text())
    manifest = json.loads((output / "manifest.jsonl").read_text())
    assert artifact == report
    assert manifest["review_type"] == "target_plan_comparison"
    assert len(manifest["artifact_sha256"]) == 64


def test_compare_refuses_nonempty_output(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(command, "compare_profiles", lambda *_args: {})
    output = tmp_path / "review"
    output.mkdir()
    (output / "keep").write_text("existing")
    args = argparse.Namespace(
        artifacts=str(tmp_path / "artifacts"),
        base_plan_id=None,
        new_plan_id=None,
        base_profile_id="base",
        new_profile_id="new",
        output=str(output),
        output_id=None,
        json=False,
    )

    assert command.cmd_compare(args) == 2
    assert "new or empty directory" in capsys.readouterr().out
