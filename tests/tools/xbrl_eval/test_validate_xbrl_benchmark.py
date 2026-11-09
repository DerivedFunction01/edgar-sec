"""Tests for validate_xbrl_benchmark CLI tool."""

import json
from pathlib import Path

from edgar_sec.tools.xbrl_eval.validate_xbrl_benchmark import main
from tests.support import cohort_registry_path, fixture_path


def test_validate_xbrl_benchmark_cli(tmp_path: Path) -> None:
    """Verify multi-firm robustness benchmark CLI passes 100% on seed cohort."""
    out_json = tmp_path / "benchmark.json"
    cohort_json = cohort_registry_path("seed_cohort.json")
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
    import edgar_sec.tools.xbrl_eval.xbrl_census as census_module

    out_json = tmp_path / "benchmark.json"
    census_out = tmp_path / "census"
    args = [
        "--output",
        str(out_json),
        "--cohort-file",
        str(cohort_registry_path("seed_cohort.json")),
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
    import edgar_sec.tools.xbrl_eval.xbrl_census as census_module
    from edgar_sec.engine.xbrl.review.benchmark import PairReport

    out_json = tmp_path / "benchmark.json"
    args = [
        "--output",
        str(out_json),
        "--cohort-file",
        str(cohort_registry_path("seed_cohort.json")),
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


def _passing_k1_summary() -> dict:
    """A K1 summary matching the pinned blocks exactly."""
    import dataclasses

    from edgar_sec.engine.xbrl.review.cross_form import K1_EXPECTATIONS

    blocks = {
        key: {f.name: getattr(exp, f.name) for f in dataclasses.fields(exp)}
        for key, exp in K1_EXPECTATIONS.items()
    }
    return {"filings": 186, "k1_blocks": blocks}


def test_validate_xbrl_benchmark_k1_gate(tmp_path: Path, monkeypatch) -> None:
    """Verify --k1 passes on pinned blocks and fails on moved mass."""
    import edgar_sec.tools.xbrl_eval.xbrl_k1_census as k1_module

    out_json = tmp_path / "benchmark.json"
    args = [
        "--output",
        str(out_json),
        "--cohort-file",
        str(cohort_registry_path("seed_cohort.json")),
        "--taxonomy-dir",
        str(fixture_path("xbrl/taxonomy")),
        "--k1",
        "--census-out",
        str(tmp_path / "k1"),
    ]
    monkeypatch.setattr(k1_module, "run_k1", lambda *a, **k: _passing_k1_summary())
    assert main(args) == 0

    moved = _passing_k1_summary()
    moved["k1_blocks"]["10-K|us-gaap"]["orphan"] += 1
    monkeypatch.setattr(k1_module, "run_k1", lambda *a, **k: moved)
    assert main(args) == 1


def _passing_cross_form_summary() -> dict:
    """A cross-form summary matching blocks, fact rows, and dei pins."""
    import dataclasses

    from edgar_sec.engine.xbrl.review.cross_form import (
        CROSS_FORM_EXPECTATIONS,
        DEI_PRESENCE_EXPECTATIONS,
        FACT_EXPECTATIONS,
    )

    blocks = {
        key: {
            "n": exp.n,
            "solved": exp.correct,
            "honest": exp.honest,
            "conflict": exp.surfaced_conflicts,
            "quarantined_facts": 0,
            "adverse": exp.adverse,
            "replay_mismatches": exp.replay_mismatches,
        }
        for key, exp in CROSS_FORM_EXPECTATIONS.items()
    }
    matrix = {
        key: {f.name: getattr(exp, f.name) for f in dataclasses.fields(exp)}
        for key, exp in FACT_EXPECTATIONS.items()
    }
    presence = {
        form: {"filings": exp.filings, "present": dict(exp.present)}
        for form, exp in DEI_PRESENCE_EXPECTATIONS.items()
    }
    return {"blocks": blocks, "fact_matrix": matrix, "dei_presence": presence}


def test_validate_xbrl_benchmark_all_gates(tmp_path: Path, monkeypatch) -> None:
    """Verify --all runs the whole standing stack green at the pins."""
    import edgar_sec.tools.xbrl_eval.xbrl_census as census_module
    import edgar_sec.tools.xbrl_eval.xbrl_cross_form_census as cross_module
    import edgar_sec.tools.xbrl_eval.xbrl_k1_census as k1_module
    from edgar_sec.engine.xbrl.review.battery import BatteryReport
    from edgar_sec.engine.xbrl.review.benchmark import PairReport

    out_json = tmp_path / "benchmark.json"
    args = [
        "--output",
        str(out_json),
        "--cohort-file",
        str(cohort_registry_path("seed_cohort.json")),
        "--taxonomy-dir",
        str(fixture_path("xbrl/taxonomy")),
        "--all",
        "--census-out",
        str(tmp_path / "gates"),
    ]
    monkeypatch.setattr(
        census_module, "run_census", lambda *a, **k: _passing_census_summary()
    )
    monkeypatch.setattr(
        cross_module, "run_cross_form", lambda *a, **k: _passing_cross_form_summary()
    )
    monkeypatch.setattr(
        census_module,
        "run_pair_gate",
        lambda: PairReport(total=17, passed=17, failures=()),
    )
    monkeypatch.setattr(
        census_module,
        "run_battery_gate",
        lambda: BatteryReport(total=188, passed=188, failures=(), results=()),
    )
    monkeypatch.setattr(k1_module, "run_k1", lambda *a, **k: _passing_k1_summary())
    assert main(args) == 0
