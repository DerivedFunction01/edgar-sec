"""Tests for apps.runner coordinator and configuration."""

from __future__ import annotations

from pathlib import Path
import pytest

from edgar_sec.apps.runner.config import FilingQuery, PipelineConfig
from edgar_sec.apps.runner.coordinator import PipelineRunner
from edgar_sec.domain.filing_catalog.filters import DateInterval, DateRange


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


def test_pipeline_runner_raises_when_no_catalog_discovered(tmp_path: Path) -> None:
    runner = PipelineRunner(PipelineConfig(artifacts_root=tmp_path))
    config = PipelineConfig(forms=("4",), artifacts_root=tmp_path)

    with pytest.raises(RuntimeError, match="no active filing catalog"):
        runner.run(config)
