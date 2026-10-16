"""Tests for artifact cleanup engine and pipeline cleanup policies."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.apps.client.models import FilingsResult
from edgar_sec.apps.runner.cleanup import (
    clear_plans,
    clear_transient,
    prune_all_ephemeral,
)
from edgar_sec.apps.runner.config import PipelineConfig
from edgar_sec.apps.runner.coordinator import PipelineRunner
from edgar_sec.foundation.runtime.paths import (
    PLANS_DIR,
    TRANSIENT_DIR,
)


def test_clear_transient_specific_and_all(tmp_path: Path) -> None:
    """Verify clearing a specific transient run and all runs."""
    run1 = tmp_path / TRANSIENT_DIR / "document_acquisition" / "run-001"
    run2 = tmp_path / TRANSIENT_DIR / "document_acquisition" / "run-002"
    run1.mkdir(parents=True)
    run2.mkdir(parents=True)
    (run1 / "state.sqlite").write_text("dummy")
    (run2 / "state.sqlite").write_text("dummy")

    assert (
        clear_transient(tmp_path, dataset="document_acquisition", run_id="run-001") == 1
    )
    assert not run1.exists()
    assert run2.exists()

    assert clear_transient(tmp_path) == 1
    assert not run2.exists()


def test_clear_plans_specific_and_all(tmp_path: Path) -> None:
    """Verify clearing a specific plan directory and all plans."""
    plan1 = tmp_path / "document_planning" / PLANS_DIR / "plan-001"
    plan2 = tmp_path / "document_planning" / PLANS_DIR / "plan-002"
    plan1.mkdir(parents=True)
    plan2.mkdir(parents=True)
    (plan1 / "plan.json").write_text("{}")
    (plan2 / "plan.json").write_text("{}")

    assert clear_plans(tmp_path, dataset="document_planning", plan_id="plan-001") == 1
    assert not plan1.exists()
    assert plan2.exists()

    assert clear_plans(tmp_path) == 1
    assert not plan2.exists()


def test_prune_all_ephemeral(tmp_path: Path) -> None:
    """Verify pruning all transient runs and plans in workspace."""
    run_dir = tmp_path / TRANSIENT_DIR / "test_ds" / "run-1"
    plan_dir = tmp_path / "test_ds" / PLANS_DIR / "plan-1"
    run_dir.mkdir(parents=True)
    plan_dir.mkdir(parents=True)

    summary = prune_all_ephemeral(tmp_path)
    assert summary["transient"] >= 1
    assert summary["plans"] >= 1
    assert not run_dir.exists()
    assert not plan_dir.exists()


def test_runner_cleanup_transient_policy(monkeypatch, tmp_path: Path) -> None:
    """Verify PipelineRunner with cleanup='transient' wipes transient staging."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    targets_dir = tmp_path / "doc_plan" / "targets"
    targets_dir.mkdir(parents=True)
    parquet_path = targets_dir / "target.parquet"
    table = pa.Table.from_arrays(
        [
            pa.array(["0000320193-23-000106"]),
            pa.array(["10-K"]),
            pa.array(["2023-11-03"]),
            pa.array(
                [
                    "https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/aapl.htm"
                ]
            ),
            pa.array(["matched"]),
        ],
        names=["accession", "form", "filing_date", "target_url", "status"],
    )
    pq.write_table(table, parquet_path)

    config = PipelineConfig(
        ciks=("0000320193",),
        forms=("10-K",),
        artifacts_root=tmp_path,
        cleanup="transient",
    )
    runner = PipelineRunner(config)

    run_dir = (
        runner.acquisition_paths.artifacts_root
        / TRANSIENT_DIR
        / "document_acquisition"
        / "run-test-clean"
    )
    staging_dir = run_dir / "staging"
    staging_dir.mkdir(parents=True)
    staged_file = staging_dir / "aapl-20230930.htm"
    staged_file.write_text("AAPL 10-K body content")

    monkeypatch.setattr(runner, "_resolve_target_ciks", lambda cfg: ("0000320193",))
    monkeypatch.setattr(runner, "_create_ephemeral_cohort", lambda ciks: "cohort-1")
    monkeypatch.setattr(runner, "_resolve_catalog_plan", lambda cfg, ch: "cat-plan-1")
    monkeypatch.setattr(
        "edgar_sec.apps.runner.coordinator.create_document_plan",
        lambda *args, **kwargs: type("Plan", (), {"plan_id": "doc-plan-1"}),
    )
    monkeypatch.setattr(
        "edgar_sec.apps.runner.coordinator.project_acquisition_run",
        lambda *args, **kwargs: type("Proj", (), {"run_id": "run-test-clean"}),
    )
    monkeypatch.setattr(
        "edgar_sec.apps.runner.coordinator.execute_acquisition_run",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        type(runner.planning_paths),
        "plan_dir",
        lambda self, pid: tmp_path / "doc_plan",
    )

    res = runner.run(config)
    assert not run_dir.exists()
    assert len(res) == 1
