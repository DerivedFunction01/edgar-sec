from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.foundation.runtime.paths import PLAN_FILE_NAME
from edgar_sec.pipelines.document_inventory.discovery import (
    discover_fixtures,
    discover_plans,
    fixture_summary,
    plan_summary,
    resolve_fixture_choice,
    resolve_plan_choice,
)
from edgar_sec.pipelines.document_inventory.fixture_store.capture import (
    create_index_fixture,
)
from edgar_sec.pipelines.document_inventory.paths import resolve_index_fixture_paths
from edgar_sec.pipelines.filing_catalog.paths import (
    resolve_filing_catalog_paths,
)


def _plan(root: Path, plan_id: str = "plan-1") -> None:
    paths = resolve_filing_catalog_paths(root)
    plan_dir = paths.plan_dir(plan_id)
    plan_dir.mkdir(parents=True)
    atomic_write_json(
        plan_dir / PLAN_FILE_NAME,
        {
            "plan_id": plan_id,
            "catalog_id": "catalog-1",
            "scope": "deterministic",
            "forms": ["10-K"],
            "unique_locators_count": 2,
            "selected_rows": 3,
        },
    )


def test_discovery_empty_tree_is_empty(tmp_path: Path) -> None:
    assert discover_plans(tmp_path) == []
    assert discover_fixtures(tmp_path) == []


def test_plan_discovery_reads_manifest_without_parquet(tmp_path: Path) -> None:
    _plan(tmp_path)
    plans = discover_plans(tmp_path)
    assert len(plans) == 1
    assert plan_summary(plans[0])["plan_id"] == "plan-1"


def test_fixture_discovery_reads_manifest_only(tmp_path: Path) -> None:
    paths = resolve_index_fixture_paths(tmp_path, "fixture-1")
    create_index_fixture(paths, fixture_id="fixture-1")
    fixtures = discover_fixtures(tmp_path)
    assert len(fixtures) == 1
    summary = fixture_summary(fixtures[0])
    assert summary["fixture_id"] == "fixture-1"
    assert summary["capture_state"] == "empty"
    assert summary["accession_count"] == 0


def test_damaged_manifests_are_skipped(tmp_path: Path) -> None:
    _plan(tmp_path)
    broken_plan = resolve_filing_catalog_paths(tmp_path).plan_dir("broken")
    broken_plan.mkdir(parents=True)
    (broken_plan / PLAN_FILE_NAME).write_text("not-json", encoding="utf-8")
    broken_fixture = resolve_index_fixture_paths(tmp_path, "broken")
    broken_fixture.root.mkdir(parents=True)
    broken_fixture.manifest_path.write_text("not-json", encoding="utf-8")
    assert [item["plan_id"] for item in discover_plans(tmp_path)] == ["plan-1"]
    assert discover_fixtures(tmp_path) == []


def test_discovery_choices_use_injected_selector() -> None:
    plans = [{"plan_id": "p1"}, {"plan_id": "p2"}]
    fixtures = [{"fixture_id": "f1"}, {"fixture_id": "f2"}]
    assert resolve_plan_choice(plans, select=lambda lines: "2") == plans[1]
    assert resolve_fixture_choice(fixtures, select=lambda lines: "1") == fixtures[0]
    assert resolve_plan_choice(plans, select=lambda lines: "bad") is None


def test_single_choice_does_not_prompt() -> None:
    plan = {"plan_id": "only"}
    assert resolve_plan_choice([plan], select=lambda _lines: pytest.fail()) == plan
