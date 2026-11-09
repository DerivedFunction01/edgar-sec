"""Tests for apps.runner coordinator and configuration."""

from __future__ import annotations

from pathlib import Path
import pytest

from edgar_sec.apps.runner.config import FilingQuery, PipelineConfig
from edgar_sec.apps.runner.coordinator import PipelineRunner, ProfileResolutionError
from edgar_sec.domain.filing_catalog.filters import DateInterval, DateRange
from edgar_sec.pipelines.document_planning.profiles import load_profile
from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.infra.storage.duckdb import connect


def test_filing_query_defaults() -> None:
    q = FilingQuery(tickers=("AAPL",), forms=("10-K",))
    assert q.tickers == ("AAPL",)
    assert q.forms == ("10-K",)
    assert q.roles == ("primary",)
    assert q.operations == ("raw",)
    assert q.dates is None
    assert q.resolved_date_selection() == ()


def test_filing_query_typed_date_resolution() -> None:
    q_range = FilingQuery(dates=DateRange.year(2023))
    assert q_range.resolved_date_string() == "2023-01-01..2023-12-31"

    q_interval = FilingQuery(dates=DateInterval.quarters(1))
    assert q_interval.resolved_date_string() == "@Q1"


def test_pipeline_config_inherits_and_adds_policies(tmp_path: Path) -> None:
    cfg = PipelineConfig(
        tickers=("AAPL",),
        forms=("10-K",),
        materialize="none",
        artifacts_root=tmp_path,
    )
    assert cfg.tickers == ("AAPL",)
    assert cfg.forms == ("10-K",)
    assert cfg.materialize == "none"
    assert cfg.artifacts_root == tmp_path


def test_pipeline_runner_resolves_profile_id(tmp_path: Path) -> None:
    runner = PipelineRunner(PipelineConfig(artifacts_root=tmp_path))
    assert runner._resolve_profile_id(("primary",)) == "primary-only"
    assert runner._resolve_profile_id(("primary", "EX-21")) == "exhibit-ex-21"


def _profile_targets(runner: PipelineRunner, profile_id: str) -> set[tuple[str, str]]:
    profile = load_profile(profile_id, runner.planning_paths.profiles_root)
    return {
        (target.role, target.type)
        for rule in profile.rules
        for target in rule.targets
    }


def test_pipeline_runner_resolves_generic_exhibit_role(tmp_path: Path) -> None:
    runner = PipelineRunner(PipelineConfig(artifacts_root=tmp_path))
    profile_id = runner._resolve_profile_id(("primary", "exhibits"))
    assert profile_id.startswith("roles-")
    assert _profile_targets(runner, profile_id) == {
        ("primary", "primary"),
        ("exhibit", "EX-*"),
    }


def test_pipeline_runner_resolves_multiple_exhibit_types(tmp_path: Path) -> None:
    runner = PipelineRunner(PipelineConfig(artifacts_root=tmp_path))
    first = runner._resolve_profile_id(("EX-99.2", "primary", "EX-99.1"))
    second = runner._resolve_profile_id(("primary", "EX-99.1", "EX-99.2"))
    assert first == second
    assert _profile_targets(runner, first) == {
        ("primary", "primary"),
        ("exhibit", "EX-99.1"),
        ("exhibit", "EX-99.2"),
    }


def test_pipeline_runner_generic_exhibit_subsumes_concrete(tmp_path: Path) -> None:
    runner = PipelineRunner(PipelineConfig(artifacts_root=tmp_path))
    profile_id = runner._resolve_profile_id(("exhibit", "EX-99.1"))
    assert _profile_targets(runner, profile_id) == {
        ("primary", "primary"),
        ("exhibit", "EX-*"),
    }


def test_pipeline_runner_resolves_linkbase_role(tmp_path: Path) -> None:
    runner = PipelineRunner(PipelineConfig(artifacts_root=tmp_path))
    profile_id = runner._resolve_profile_id(("linkbases",))
    assert _profile_targets(runner, profile_id) == {
        ("primary", "primary"),
        ("data_file", "EX-101.*"),
    }


def test_pipeline_runner_refuses_unknown_role(tmp_path: Path) -> None:
    runner = PipelineRunner(PipelineConfig(artifacts_root=tmp_path))
    with pytest.raises(ProfileResolutionError, match="banana"):
        runner._resolve_profile_id(("primary", "banana"))


def test_pipeline_runner_refuses_unplannable_exhibit_type(tmp_path: Path) -> None:
    runner = PipelineRunner(PipelineConfig(artifacts_root=tmp_path))
    with pytest.raises(ProfileResolutionError):
        runner._resolve_profile_id(("EX-101.*",))


def test_pipeline_runner_plan_shape_splits_run_intents(tmp_path: Path) -> None:
    runner = PipelineRunner(PipelineConfig(artifacts_root=tmp_path))
    profile_id = runner._resolve_profile_id(("primary", "exhibits"))
    plan_profile_id, intents = runner._plan_shape(profile_id)
    assert plan_profile_id == "primary-only"
    assert [(intent.role, intent.type, intent.optional) for intent in intents] == [
        ("exhibit", "EX-*", True)
    ]
    concrete_id = runner._resolve_profile_id(("primary", "EX-99.1", "EX-99.2"))
    plan_profile_id, intents = runner._plan_shape(concrete_id)
    assert plan_profile_id == "primary-only"
    assert [(intent.role, intent.type) for intent in intents] == [
        ("exhibit", "EX-99.1"),
        ("exhibit", "EX-99.2"),
    ]
    assert runner._plan_shape("primary-only") == ("primary-only", ())


def test_pipeline_runner_raises_when_no_catalog_discovered(tmp_path: Path) -> None:
    runner = PipelineRunner(PipelineConfig(artifacts_root=tmp_path))
    config = PipelineConfig(forms=("4",), artifacts_root=tmp_path)

    with pytest.raises(RuntimeError, match="no active filing catalog"):
        runner.run(config)


def test_pipeline_runner_ingests_large_cik_file_out_of_core(tmp_path: Path) -> None:
    source = tmp_path / "ciks.csv"
    source.write_text(
        "cik\n" + "".join(f"{value}\n" for value in range(1, 1001)) + "1\n"
    )
    runner = PipelineRunner(PipelineConfig(artifacts_root=tmp_path))

    cohort_id = runner._resolve_target_cohort(FilingQuery(input_file=source))
    assert cohort_id is not None
    record = CohortCatalog(runner.cohort_paths).get_cohort(cohort_id)
    assert record is not None
    dataset = runner.cohort_paths.resolve_relative_path(record.dataset_path)
    with connect() as con:
        assert (
            con.execute(
                "SELECT count(*) FROM read_parquet(?)", [str(dataset)]
            ).fetchone()[0]
            == 1000
        )
        assert (
            con.execute(
                "SELECT cik_padded FROM read_parquet(?) ORDER BY ordinal LIMIT 1",
                [str(dataset)],
            ).fetchone()[0]
            == "0000000001"
        )

    assert runner._resolve_target_cohort(FilingQuery(input_file=source)) == cohort_id


def test_pipeline_runner_rejects_invalid_cik_file_rows(tmp_path: Path) -> None:
    source = tmp_path / "invalid-ciks.csv"
    source.write_text("cik\nnot-a-cik\n")
    runner = PipelineRunner(PipelineConfig(artifacts_root=tmp_path))

    with pytest.raises(ValueError):
        runner._resolve_target_cohort(FilingQuery(input_file=source))
