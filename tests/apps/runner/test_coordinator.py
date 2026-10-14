"""Tests for apps.runner coordinator and configuration."""

from __future__ import annotations

import pytest

from edgar_sec.apps.runner.config import RunnerOptions, TargetSpec
from edgar_sec.apps.runner.coordinator import PipelineRunner


def test_target_spec_defaults_and_tuples() -> None:
    spec = TargetSpec(forms=("4",), ciks=("320193",), limit=10)
    assert spec.forms == ("4",)
    assert spec.ciks == ("320193",)
    assert spec.role == "primary"
    assert spec.limit == 10
    assert spec.input_file is None


def test_runner_options_defaults() -> None:
    options = RunnerOptions()
    assert options.operation == "raw"
    assert options.use_broker is True
    assert options.workers is None
    assert options.publish_snapshot is True

    custom = RunnerOptions(
        operation="raw",
        family_operations={"4": "render_to_xml", "10-K": "render_to_txt"},
    )
    assert custom.resolve_operation("4") == "render_to_xml"
    assert custom.resolve_operation("10-K") == "render_to_txt"
    assert custom.resolve_operation("8-K") == "raw"

    auto_options = RunnerOptions(operation="auto")
    assert auto_options.resolve_operation("4") == "render_to_xml"
    assert auto_options.resolve_operation("10-K") == "render_to_txt"
    assert auto_options.resolve_operation("10-Q") == "render_to_txt"
    assert auto_options.resolve_operation("8-K") == "render_to_txt"
    assert auto_options.resolve_operation("UNKNOWN") == "raw"


def test_pipeline_runner_resolves_profile_id() -> None:
    runner = PipelineRunner(RunnerOptions())
    primary_spec = TargetSpec(role="primary")
    exhibit_spec = TargetSpec(role="EX-21")

    assert runner._resolve_profile_id(primary_spec) == "primary-only"
    assert runner._resolve_profile_id(exhibit_spec) == "exhibit-ex-21"


def test_pipeline_runner_raises_when_no_catalog_discovered(tmp_path) -> None:
    runner = PipelineRunner(RunnerOptions(artifacts_root=tmp_path))
    spec = TargetSpec(forms=("4",))

    with pytest.raises(RuntimeError, match="no active filing catalog"):
        runner.run(spec)
