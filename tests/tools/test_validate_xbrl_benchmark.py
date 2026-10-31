"""Tests for validate_xbrl_benchmark CLI tool."""

import json
from pathlib import Path

from edgar_sec.tools.validate_xbrl_benchmark import main
from tests.support import fixture_path


def test_validate_xbrl_benchmark_cli(tmp_path: Path) -> None:
    """Verify multi-firm robustness benchmark CLI passes 100% on seed cohort."""
    out_json = tmp_path / "benchmark.json"
    cohort_json = fixture_path("xbrl/seed_cohort.json")
    tax_dir = fixture_path("xbrl/taxonomy")
    ret = main(
        [
            "--output",
            str(out_json),
            "--cohort-file",
            str(cohort_json),
            "--taxonomy-dir",
            str(tax_dir),
        ]
    )
    assert ret == 0
    assert out_json.exists()
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    summary = payload["summary"]
    assert summary["accuracy_pct"] == 100.0
    assert summary["failed_tests"] == 0
    assert summary["passed_tests"] > 0
    assert summary["firm_count"] == 49


def test_validate_xbrl_benchmark_default_cohort_is_canonical(
    tmp_path: Path,
) -> None:
    """Verify the default cohort is the canonical 49-filing registry."""
    out_json = tmp_path / "benchmark_default.json"
    ret = main(["--output", str(out_json)])
    assert ret == 0
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["summary"]["firm_count"] == 49


def test_validate_xbrl_benchmark_missing_cohort() -> None:
    """Verify non-zero return code when cohort file is missing."""
    ret = main(["--cohort-file", "/nonexistent/cohort.json"])
    assert ret == 1


def _passing_census_summary() -> dict:
    """A census summary matching the scored expectations exactly."""
    from edgar_sec.engine.xbrl.review.benchmark import CENSUS_EXPECTATIONS

    populations = {}
    for name, exp in CENSUS_EXPECTATIONS.items():
        populations[name] = {
            "n": exp.n,
            "classification": {
                "correct": exp.correct,
                "honest-faithful": exp.honest,
            },
            "replay_mismatches": 0,
            "surfaced_conflicts": [{}] * exp.surfaced_conflicts,
            "derived_artefacts": [],
            "near_guard_violations": [],
            "textblock_answer_evaluations": 0,
        }
    return {"populations": populations}


def test_validate_xbrl_benchmark_census_gate(tmp_path: Path, monkeypatch) -> None:
    """Verify --census passes on scored counts and fails on a moved count."""
    import edgar_sec.tools.xbrl_census as census_module

    out_json = tmp_path / "benchmark.json"
    census_out = tmp_path / "census"
    args = [
        "--output",
        str(out_json),
        "--cohort-file",
        str(fixture_path("xbrl/seed_cohort.json")),
        "--taxonomy-dir",
        str(fixture_path("xbrl/taxonomy")),
        "--census",
        "--census-out",
        str(census_out),
    ]
    monkeypatch.setattr(
        census_module, "run_census", lambda *a, **k: _passing_census_summary()
    )
    assert main(args) == 0
    assert (census_out / "summary.json").exists()

    moved = _passing_census_summary()
    moved["populations"]["probe"]["classification"]["correct"] -= 1
    monkeypatch.setattr(census_module, "run_census", lambda *a, **k: moved)
    assert main(args) == 1


def test_validate_xbrl_benchmark_pairs_gate(tmp_path: Path, monkeypatch) -> None:
    """Verify --pairs passes on a clean pair report and fails on a regression."""
    import edgar_sec.tools.xbrl_census as census_module
    from edgar_sec.engine.xbrl.review.benchmark import PairReport

    out_json = tmp_path / "benchmark.json"
    args = [
        "--output",
        str(out_json),
        "--cohort-file",
        str(fixture_path("xbrl/seed_cohort.json")),
        "--taxonomy-dir",
        str(fixture_path("xbrl/taxonomy")),
        "--pairs",
    ]
    monkeypatch.setattr(
        census_module,
        "run_pair_gate",
        lambda: PairReport(total=14, passed=14, failures=()),
    )
    assert main(args) == 0
    monkeypatch.setattr(
        census_module,
        "run_pair_gate",
        lambda: PairReport(
            total=14, passed=13, failures=("pair: expected tier=exact",)
        ),
    )
    assert main(args) == 1
