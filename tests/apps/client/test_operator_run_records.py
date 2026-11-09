"""Tests for the operator's run-record machinery module."""

from __future__ import annotations

import pytest

from edgar_sec.apps.client import operator, operator_run_records


def test_registry_contains_record_rows() -> None:
    ids = {spec.id for spec in operator_run_records.build_specs()}
    assert ids == {"past_runs", "inspect_past_run", "rerun_past_run"}
    assert ids <= set(operator.REGISTRY)
    assert operator_run_records.SPECS
    assert operator_run_records.GATHERERS == {}
    registry: dict = {}
    operator_run_records.register(registry)
    assert set(registry) == ids
    with pytest.raises(ValueError):
        operator_run_records.register(registry)


def test_engine_taken_routing_rule() -> None:
    assert operator_run_records.engine_taken("fast", ("primary",), (), None) == "fast"
    assert (
        operator_run_records.engine_taken("fast", ("primary",), ("a",), None)
        == "pipeline"
    )
    assert (
        operator_run_records.engine_taken("fast", ("ex-101",), (), None) == "pipeline"
    )
    assert (
        operator_run_records.engine_taken("snapshot", ("primary",), (), None)
        == "snapshot"
    )
    assert (
        operator_run_records.engine_taken("pipeline", ("primary",), (), None)
        == "pipeline"
    )


def test_cache_line_deltas_and_absence() -> None:
    before = {"hits": 1, "nested": {"entries": 5}}
    after = {"hits": 3, "nested": {"entries": 5}}
    line = operator_run_records.cache_line(before, after)
    assert line is not None
    assert line["delta"] == {"hits": 2}
    assert operator_run_records.cache_line(None, after) is None
    assert operator_run_records.cache_line(before, None) is None


def test_member_accounting_payload_and_missing_members() -> None:
    payload = [
        {"accession": "a1", "outcome": "acquired"},
        {"accession": "a2", "outcome": "failed"},
        {"accession": "a3", "outcome": "planned"},
    ]
    accounting = operator_run_records.member_accounting(
        ["a1", "a2"], payload, ["a1", "a2", "a9"]
    )
    assert accounting["success_count"] == 1
    assert accounting["other_count"] == 1
    assert accounting["errors"] == [
        {"accession": "a2", "error_code": "external_failure", "outcome": "failed"},
        {
            "accession": "a9",
            "error_code": "external_failure",
            "outcome": "not_returned",
        },
    ]
    assert operator_run_records.member_accounting(["a1"], None)["success_count"] == 1
