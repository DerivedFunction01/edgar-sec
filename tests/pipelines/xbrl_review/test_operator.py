"""Tests for XBRL review operator console and menus."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from edgar_sec.infra.storage.review.models import DiffSummary
from edgar_sec.pipelines.xbrl_review import operator as operator_module
from edgar_sec.pipelines.xbrl_review.operator import build_operator_menu, main
from edgar_sec.pipelines.xbrl_review.review import ReviewRun


def test_build_operator_menu() -> None:
    """Verify operator menu actions are built correctly."""
    actions = build_operator_menu()
    labels = [a.label for a in actions]
    assert any("project" in l.lower() for l in labels)
    assert any("review run" in l.lower() for l in labels)
    assert any("compare" in l.lower() for l in labels)
    assert any("promote" in l.lower() for l in labels)
    assert any("dag" in l.lower() for l in labels)


def _pick(items, prompt_label="", default=None):
    if "base" in prompt_label:
        return items[1]
    return items[0]


def test_generate_review_renders_result_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Verify the generate result block renders as aligned key-values."""
    cohort_file = tmp_path / "cohort.json"
    cohort_file.write_text(json.dumps([{"accession": "a-1"}]), encoding="utf-8")
    run_dir = tmp_path / "run-test"
    monkeypatch.setattr(
        operator_module,
        "discover_cohorts",
        lambda: [{"label": "Specimen", "path": cohort_file}],
    )
    monkeypatch.setattr(operator_module, "prompt_paginated_choice", _pick)
    monkeypatch.setattr(
        operator_module,
        "execute_review_generation",
        lambda filings: ReviewRun(
            run_id="run-test",
            run_dir=run_dir,
            total_filings=len(filings),
            solved_count=42,
            quarantine_count=5,
            hypotheses_count=9,
        ),
    )
    operator_module._action_generate_review()
    out = capsys.readouterr().out
    assert "Review run created: run-test" in out
    assert "  Total filings  1\n" in out
    assert "  Solved nodes   42\n" in out
    assert "  Quarantined    5\n" in out
    assert "  Hypotheses     9\n" in out
    assert f"  Output path    {run_dir}\n" in out


def test_compare_runs_renders_summary_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Verify the compare summary renders as aligned key-values."""
    base_dir = tmp_path / "run-base"
    new_dir = tmp_path / "run-new"
    runs = [
        {
            "run_id": "run-new",
            "total_filings": 3,
            "total_hypotheses": 9,
            "path": new_dir,
        },
        {
            "run_id": "run-base",
            "total_filings": 2,
            "total_hypotheses": 4,
            "path": base_dir,
        },
    ]
    monkeypatch.setattr(operator_module, "discover_review_runs", lambda: runs)
    monkeypatch.setattr(operator_module, "prompt_paginated_choice", _pick)
    monkeypatch.setattr(
        operator_module,
        "xbrl_paths",
        lambda: SimpleNamespace(review_runs_root=tmp_path),
    )
    monkeypatch.setattr(
        operator_module,
        "compare_review_runs",
        lambda **_kw: DiffSummary(
            base_run=str(base_dir),
            new_run=str(new_dir),
            total_cases=7,
            unchanged_count=4,
            changed_count=2,
            added_count=1,
            removed_count=0,
            component_breakdown=(),
            case_diffs=(),
        ),
    )
    operator_module._action_compare_runs()
    out = capsys.readouterr().out
    diff_report = tmp_path / "diff-run-base_vs_run-new" / "summary.txt"
    assert "Comparison Summary" in out
    assert "  Total cases  7\n" in out
    assert "  Unchanged    4\n" in out
    assert "  Changed      2\n" in out
    assert "  Added        1\n" in out
    assert "  Removed      0\n" in out
    assert f"  Diff report  {diff_report}\n" in out


def test_operator_main_delegates_to_cli() -> None:
    """Verify operator entrypoint forwards non-empty argv to CLI."""
    with pytest.raises(SystemExit) as exc_info:
        main(["--help"])
    assert exc_info.value.code == 0
