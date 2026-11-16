"""Tests for deterministic classification planning."""

from __future__ import annotations

import pytest

from edgar_sec.infra.storage.parquet import read_parquet_table
from edgar_sec.pipelines.table_classification.paths import ClassificationPaths
from edgar_sec.pipelines.table_classification.planner import (
    DocumentTargetRow,
    FilingRow,
    PlanError,
    build_plan,
    read_plan,
    work_item_id_for,
)
from edgar_sec.pipelines.table_classification.schemas import PLAN_RELATION_SCHEMAS

from .support import make_request


def test_build_and_read_round_trip(tmp_path) -> None:  # noqa: ANN001
    paths = ClassificationPaths(artifacts_root=tmp_path / "artifacts")
    result = build_plan(make_request(), paths)
    assert not result.reused
    assert result.plan_id.startswith("tcplan-")
    for relation, schema in PLAN_RELATION_SCHEMAS.items():
        table = read_parquet_table(paths.plan_relation_path(result.plan_id, relation))
        assert table.schema.equals(schema)
    plan = read_plan(paths, result.plan_id)
    assert plan.provenance["registry_state"] == "registry:test-v1"
    assert plan.provenance["source_snapshot_id"] == "snap-test-1"
    assert plan.provenance["filing_count"] == 2
    assert plan.provenance["profile_count"] == 1
    assert plan.provenance["target_count"] == 3
    assert plan.provenance["work_item_count"] == 2
    assert [filing.accession for filing in plan.filings] == [
        "0000000001-26-000001",
        "0000000002-26-000001",
    ]
    assert len(plan.work_items) == 2
    for item in plan.work_items:
        assert item.work_item_id == work_item_id_for(result.plan_id, item.accession)
    targets = plan.targets_for("0000000001-26-000001")
    assert [(t.target_role, t.target_type, t.optional) for t in targets] == [
        ("exhibit", "EX-13", True),
        ("primary", "10-K", False),
    ]


def test_identical_request_reuses_plan(tmp_path) -> None:  # noqa: ANN001
    paths = ClassificationPaths(artifacts_root=tmp_path / "artifacts")
    first = build_plan(make_request(), paths)
    second = build_plan(make_request(), paths)
    assert second.plan_id == first.plan_id
    assert second.reused


def test_registry_change_plans_a_new_run(tmp_path) -> None:  # noqa: ANN001
    paths = ClassificationPaths(artifacts_root=tmp_path / "artifacts")
    first = build_plan(make_request(), paths)
    changed = build_plan(make_request(registry_state="registry:test-v2"), paths)
    assert changed.plan_id != first.plan_id
    assert not changed.reused


def test_created_at_is_not_plan_identity(tmp_path) -> None:  # noqa: ANN001
    paths = ClassificationPaths(artifacts_root=tmp_path / "artifacts")
    first = build_plan(make_request(), paths)
    later = build_plan(make_request(created_at="2026-11-16T00:00:00Z"), paths)
    assert later.plan_id == first.plan_id
    assert later.reused


def test_duplicate_accession_is_refused(tmp_path) -> None:  # noqa: ANN001
    paths = ClassificationPaths(artifacts_root=tmp_path / "artifacts")
    filing = FilingRow("0000000001-26-000001", 1, "10-K")
    with pytest.raises(PlanError):
        build_plan(make_request(filings=(filing, filing)), paths)


def test_unplanned_profile_accession_is_refused(tmp_path) -> None:  # noqa: ANN001
    paths = ClassificationPaths(artifacts_root=tmp_path / "artifacts")
    from edgar_sec.pipelines.table_classification.planner import ProfileApplicationRow

    rows = (ProfileApplicationRow("9999999999-26-000001", "ppe", "family", "seat"),)
    with pytest.raises(PlanError):
        build_plan(make_request(profile_application=rows), paths)


def test_bad_geometry_route_is_refused(tmp_path) -> None:  # noqa: ANN001
    paths = ClassificationPaths(artifacts_root=tmp_path / "artifacts")
    targets = (
        DocumentTargetRow(
            "0000000001-26-000001",
            "primary",
            "10-K",
            False,
            "acme.htm",
            "expected",
            "carrier_pigeon",
        ),
    )
    with pytest.raises(PlanError):
        build_plan(make_request(document_targets=targets), paths)
