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
                total=1,
                completed=1,
                fixture_verification_failure=0,
                execution_error=0,
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


def test_review_analyze_delegates_selected_runs_and_emits_json(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    calls = []
    report = {"schema_version": 1, "runs": [{"review_id": "run-a"}]}
    monkeypatch.setattr(
        review,
        "analyze_review_runs",
        lambda runs, *, output: calls.append((runs, output)) or report,
    )
    run_path = tmp_path / "run-a"
    run_path.mkdir()
    output_path = tmp_path / "analysis.json"

    assert (
        review.cmd_review_analyze(
            SimpleNamespace(
                run=[str(run_path)], output=str(output_path), artifacts="", json=True
            )
        )
        == 0
    )

    assert calls == [((run_path,), output_path)]
    assert json.loads(capsys.readouterr().out) == report


def test_review_label_validates_run_before_writing_sidecar(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    root = tmp_path / "review"
    artifact_path = root / "cases" / "case-a" / "processing-review.json"
    artifact = {"artifact_sha256": "a" * 64}
    calls = []
    monkeypatch.setattr(
        review,
        "load_processing_review_artifact",
        lambda path: (root, artifact) if path == artifact_path else None,
    )
    monkeypatch.setattr(
        review,
        "analyze_review_runs",
        lambda runs: calls.append(("validate", runs)),
    )
    label = {
        "artifact_sha256": "b" * 64,
        "target_id": "target-a",
        "outcome": "positive",
    }
    monkeypatch.setattr(
        review,
        "build_review_label",
        lambda source, **kwargs: calls.append(("build", source, kwargs)) or label,
    )
    label_path = root / "labels" / "label.json"
    monkeypatch.setattr(
        review,
        "write_review_label",
        lambda run, source, record: (
            calls.append(("write", run, source, record)) or label_path
        ),
    )

    assert (
        review.cmd_review_label(
            SimpleNamespace(
                artifact=str(artifact_path),
                outcome="positive",
                observed_kind="exhibit",
                observed_authority="reg_s_k_item_601",
                observed_code="3.1",
                annotator_id="reviewer-a",
                annotated_at_utc="2026-10-13T20:00:00Z",
                evidence_ref="text:0-40",
                rationale="matches",
                annotation_kind="independent",
                supersedes=None,
                json=True,
            )
        )
        == 0
    )

    assert calls[0] == ("validate", (root,))
    assert calls[1][0] == "build"
    assert calls[2] == ("write", root, artifact, label)
    assert json.loads(capsys.readouterr().out)["label_sha256"] == "b" * 64


def test_review_holdout_loads_a_frozen_spec_and_emits_report(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    run = tmp_path / "review-run"
    run.mkdir()
    spec_path = tmp_path / "holdout.json"
    spec = {"schema_version": 1, "protocol_id": "holdout-v1"}
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    output = tmp_path / "holdout-report.json"
    calls = []
    report = {"protocol_id": "holdout-v1", "labeled_holdout_cases": 2}
    monkeypatch.setattr(
        review,
        "analyze_holdout_review_run",
        lambda selected_run, selected_spec, *, output: (
            calls.append((selected_run, selected_spec, output)) or report
        ),
    )

    assert (
        review.cmd_review_holdout(
            SimpleNamespace(
                run=str(run),
                spec=str(spec_path),
                output=str(output),
                artifacts="",
                json=True,
            )
        )
        == 0
    )

    assert calls == [(run, spec, output)]
    assert json.loads(capsys.readouterr().out) == report


def test_review_compare_validates_both_runs_before_shared_case_diff(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    calls = []
    base = tmp_path / "base"
    new = tmp_path / "new"
    base.mkdir()
    new.mkdir()
    output = tmp_path / "diff"
    monkeypatch.setattr(
        review,
        "analyze_review_runs",
        lambda runs, **_kwargs: calls.append(("validate", runs)) or {},
    )
    monkeypatch.setattr(
        review,
        "compare_review_runs",
        lambda **kwargs: (
            calls.append(("diff", kwargs))
            or SimpleNamespace(
                base_run="base",
                new_run="new",
                total_cases=1,
                unchanged_count=1,
                changed_count=0,
                added_count=0,
                removed_count=0,
            )
        ),
    )

    assert (
        review.cmd_review_compare(
            SimpleNamespace(
                base=str(base),
                new=str(new),
                output=str(output),
                max_display=10,
                artifacts=str(tmp_path),
                json=True,
            )
        )
        == 0
    )

    assert calls[0] == ("validate", (base, new))
    assert calls[1][0] == "diff"
    assert calls[1][1]["base_dir"] == base
    assert calls[1][1]["new_dir"] == new
    assert calls[1][1]["output_dir"] == output
    assert json.loads(capsys.readouterr().out)["unchanged"] == 1
