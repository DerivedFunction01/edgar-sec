"""Unit and contract tests for Phase 02 target plan (full and fixture scopes)."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from defs.runtime.artifacts import make_manifest, publish_manifest
from defs.storage import pa, write_table_atomic

target_plan = importlib.import_module("phases.02_filing_extraction.core.target_plan")
selection_policy = importlib.import_module(
    "phases.02_filing_extraction.core.selection_policy"
)

plan = target_plan.plan
EraBand = selection_policy.EraBand
SelectionPolicy = selection_policy.SelectionPolicy


@pytest.fixture()
def catalog_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))

    manifests_root = tmp_path / "manifests"
    manifests_root.mkdir(parents=True)

    # 1. Target Parquet
    target_dir = (
        manifests_root / "filing_extraction" / "filing_targets" / "final" / "form=10-K"
    )
    target_dir.mkdir(parents=True)
    target_file = target_dir / "data.parquet"

    data = {
        "occurrence_id": ["occ1", "occ2", "occ3"],
        "document_locator_key": ["loc1", "loc2", "loc3"],
        "source_cik": ["0000000001", "0000000002", "0000000003"],
        "accession": ["acc1", "acc2", "acc3"],
        "form": ["10-K", "10-K", "10-K"],
        "is_amendment": [False, False, False],
        "filing_date": ["2022-03-01", "2023-03-01", "2024-03-01"],
        "report_date": ["2021-12-31", "2022-12-31", "2023-12-31"],
        "primary_document": ["doc.htm", "doc.htm", "doc.htm"],
        "document_path": ["data/1.htm", "data/2.htm", "data/3.htm"],
        "archive_url": ["http://sec.gov/1", "http://sec.gov/2", "http://sec.gov/3"],
        "reported_size": [100000, 200000, 300000],
        "is_xbrl": [True, True, True],
        "is_inline_xbrl": [True, True, True],
        "is_xbrl_numeric": [True, True, True],
    }
    write_table_atomic(pa.Table.from_pydict(data), target_file)

    target_manifest = make_manifest(
        dataset="filing_targets",
        phase="filing_extraction",
        run_id="cat123",
        schema_version="1.0",
        artifact_path=str(target_file),
        artifacts_root=str(tmp_path),
        row_count=3,
        partition="",
    )
    publish_manifest(target_manifest, artifacts_root=str(tmp_path))

    # 2. Profile Parquet
    profile_dir = manifests_root / "filing_extraction" / "company_profiles" / "final"
    profile_dir.mkdir(parents=True)
    profile_file = profile_dir / "company_profiles.parquet"

    prof_data = {
        "cik": ["0000000001", "0000000002", "0000000003"],
        "sic": ["1000", "2000", "3000"],
        "sic_description": ["Mining", "Manufacturing", "Tech"],
        "owner_org_cik": ["0000000001", None, None],
        "owner_org_name": ["Parent Co", None, None],
        "entity_type": ["operating", "operating", "operating"],
        "filer_category": [
            "Large Accelerated Filer",
            "Accelerated Filer",
            "Non-accelerated Filer",
        ],
        "state_of_incorporation": ["DE", "NY", "CA"],
        "state_of_business": ["CA", "TX", "WA"],
        "foreign_country_code": [None, None, "CA"],
        "company_name": ["Co One", "Co Two", "Co Three"],
    }
    write_table_atomic(pa.Table.from_pydict(prof_data), profile_file)

    profile_manifest = make_manifest(
        dataset="company_profiles",
        phase="filing_extraction",
        run_id="cat123",
        schema_version="1.0",
        artifact_path=str(profile_file),
        artifacts_root=str(tmp_path),
        row_count=3,
        partition="",
    )
    publish_manifest(profile_manifest, artifacts_root=str(tmp_path))

    return tmp_path


def test_plan_full_scope(catalog_fixture: Path) -> None:
    result = plan(
        catalog="cat123",
        scope="full",
        forms=("10-K",),
    )

    assert result["scope"] == "full"
    assert result["catalog_id"] == "cat123"
    assert result["counts"]["10-K"] == 3
    assert result["unique_locators_count"] == 3

    plan_dir = (
        catalog_fixture
        / "manifests"
        / "filing_extraction"
        / "target_plans"
        / "final"
        / result["plan_id"]
    )
    assert (plan_dir / "plan.json").is_file()
    assert (plan_dir / "targets" / "form=10-K" / "data.parquet").is_file()
    assert (plan_dir / "locator_groups.parquet").is_file()
    assert (plan_dir / "selection_report.json").is_file()


def test_plan_fixture_scope(catalog_fixture: Path) -> None:
    policy = SelectionPolicy(
        corpus_id="test_corpus",
        forms=["10-K"],
        era_bands=[
            EraBand(name="era_2021", start_year=2021, end_year=2022),
            EraBand(name="era_2022", start_year=2022, end_year=2023),
            EraBand(name="era_2023", start_year=2023, end_year=2024),
        ],
        base_content_units=2,
        reserve_size=1,
    )
    pol_file = catalog_fixture / "policy.json"
    policy.write(pol_file)

    result = plan(
        catalog="cat123",
        scope="fixture",
        selection_policy_path=pol_file,
    )

    assert result["scope"] == "fixture"
    assert result["catalog_id"] == "cat123"
    assert result["policy_corpus"] == "test_corpus"
    assert result["active_targets_count"] == 2
    assert result["reserve_count"] == 1

    plan_dir = (
        catalog_fixture
        / "manifests"
        / "filing_extraction"
        / "target_plans"
        / "final"
        / result["plan_id"]
    )
    assert (plan_dir / "plan.json").is_file()
    assert (plan_dir / "targets" / "form=10-K" / "data.parquet").is_file()
    assert (plan_dir / "locator_groups.parquet").is_file()
    assert (plan_dir / "reserve_targets.parquet").is_file()
    assert (plan_dir / "selection_report.json").is_file()
