"""Unit and contract tests for Phase 02 target plans (deterministic and policy scopes)."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from defs.storage import pa, write_table_atomic

target_plan = importlib.import_module("phases.02_filing_extraction.core.target_plan")
plan_expansion = importlib.import_module(
    "phases.02_filing_extraction.core.plan_expansion"
)
selection_policy = importlib.import_module(
    "phases.02_filing_extraction.core.selection_policy"
)

plan = target_plan.plan
expand = target_plan.expand
EraBand = selection_policy.EraBand
SelectionPolicy = selection_policy.SelectionPolicy


@pytest.fixture()
def catalog_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))

    manifests_root = tmp_path / "manifests"
    manifests_root.mkdir(parents=True)

    # 1. Target Snapshot Directory with flat shards
    snap_dir = (
        manifests_root / "filing_extraction" / "filing_catalog" / "snapshots" / "cat123"
    )
    snap_dir.mkdir(parents=True)
    target_dir = snap_dir / "filing_targets"
    target_dir.mkdir(parents=True)
    target_file = target_dir / "part-00000.parquet"

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
        "document_path_source": [
            "primary_document",
            "primary_document",
            "primary_document",
        ],
    }
    write_table_atomic(pa.Table.from_pydict(data), target_file)

    # 2. Profile Parquet
    profile_file = snap_dir / "company_profiles.parquet"

    prof_data = {
        "cik": ["0000000001", "0000000002", "0000000003"],
        "identity": [
            {"name": "Co One", "former_names": []},
            {"name": "Co Two", "former_names": []},
            {"name": "Co Three", "former_names": []},
        ],
        "classification": [
            {
                "entity_type": "operating",
                "sic_code": "1000",
                "sic_description": "Mining",
                "owner_org": None,
                "filer_category": "Large Accelerated Filer",
            },
            {
                "entity_type": "operating",
                "sic_code": "2000",
                "sic_description": "Manufacturing",
                "owner_org": None,
                "filer_category": "Accelerated Filer",
            },
            {
                "entity_type": "operating",
                "sic_code": "3000",
                "sic_description": "Tech",
                "owner_org": None,
                "filer_category": "Non-accelerated Filer",
            },
        ],
        "identifiers": [
            {"ein": None, "lei": None},
            {"ein": None, "lei": None},
            {"ein": None, "lei": None},
        ],
        "contact": [
            {
                "phone": None,
                "website": None,
                "investor_website": None,
                "description": None,
            }
        ]
        * 3,
        "incorporation": [
            {"state": "DE", "state_description": None},
            {"state": "NY", "state_description": None},
            {"state": "CA", "state_description": None},
        ],
        "reporting": [{"fiscal_year_end": "1231"}] * 3,
        "insider_transactions": [{"owner_exists": False, "issuer_exists": False}] * 3,
        "addresses": [{"mailing": None, "business": None}] * 3,
        "listings": [[]] * 3,
        "input_name": ["Co One", "Co Two", "Co Three"],
        "status": ["ok", "ok", "ok"],
        "error": [None, None, None],
        "anomalies": [[]] * 3,
        "extra_fields": [None, None, None],
        "snapshot_id": ["S0", "S0", "S0"],
        "fetched_at": ["2024-01-01T00:00:00Z"] * 3,
        "source_url": ["http://sec.gov"] * 3,
        "response_sha256": ["sha"] * 3,
        "byte_count": [1000] * 3,
        "input_fingerprint": ["fp"] * 3,
        "schema_version": ["1.0.0"] * 3,
        "profile_schema_version": ["1.0.0"] * 3,
    }
    write_table_atomic(pa.Table.from_pydict(prof_data), profile_file)

    import json

    manifest = {
        "manifest_kind": "filing_catalog_snapshot",
        "snapshot_id": "cat123",
        "catalog_id": "cat123",
        "target_rows": 3,
        "form_count": 1,
        "form_counts": {"10-K": 3},
        "company_profiles_rows": 3,
        "parts": [
            {
                "path": "filing_targets/part-00000.parquet",
                "row_count": 3,
                "artifact_sha256": "",
            }
        ],
    }
    (snap_dir / "snapshot.manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    return tmp_path


def test_plan_deterministic_scope(catalog_fixture: Path) -> None:
    result = plan(
        catalog="cat123",
        scope="deterministic",
        forms=("10-K",),
    )

    assert result["scope"] == "deterministic"
    assert result["catalog_id"] == "cat123"
    assert result["counts"]["10-K"] == 3
    assert result["unique_locators_count"] == 3

    plan_dir = (
        catalog_fixture
        / "manifests"
        / "filing_extraction"
        / "target_plans"
        / result["plan_id"]
    )
    assert (plan_dir / "plan.json").is_file()
    assert (plan_dir / "targets" / "form=10-K" / "data.parquet").is_file()
    assert (plan_dir / "locator_groups.parquet").is_file()
    assert (plan_dir / "selection_report.json").is_file()
    assert not list(plan_dir.parent.glob(".staging-*"))


def test_plan_deterministic_scope_reuses_existing_bundle(
    catalog_fixture: Path,
) -> None:
    first = plan(
        catalog="cat123",
        scope="deterministic",
        forms=("10-K",),
    )
    plan_dir = (
        catalog_fixture
        / "manifests"
        / "filing_extraction"
        / "target_plans"
        / first["plan_id"]
    )
    marker = plan_dir / "reuse_marker.txt"
    marker.write_text("untouched", encoding="utf-8")

    second = plan(
        catalog="cat123",
        scope="deterministic",
        forms=("10-K",),
    )

    assert second == first
    assert marker.is_file()


def test_plan_deterministic_scope_fails_on_incomplete_bundle(
    catalog_fixture: Path,
) -> None:
    first = plan(
        catalog="cat123",
        scope="deterministic",
        forms=("10-K",),
    )
    plan_dir = (
        catalog_fixture
        / "manifests"
        / "filing_extraction"
        / "target_plans"
        / first["plan_id"]
    )
    (plan_dir / "locator_groups.parquet").unlink()

    with pytest.raises(ValueError, match="incomplete or conflicts"):
        plan(
            catalog="cat123",
            scope="deterministic",
            forms=("10-K",),
        )
    assert plan_dir.is_dir()


def test_plan_policy_scope(catalog_fixture: Path) -> None:
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
        scope="policy",
        selection_policy_path=pol_file,
    )

    assert result["scope"] == "policy"
    assert result["catalog_id"] == "cat123"
    assert result["policy_corpus"] == "test_corpus"
    assert result["active_targets_count"] == 2
    assert result["reserve_count"] == 1

    plan_dir = (
        catalog_fixture
        / "manifests"
        / "filing_extraction"
        / "target_plans"
        / result["plan_id"]
    )
    assert (plan_dir / "plan.json").is_file()
    assert (plan_dir / "targets" / "form=10-K" / "data.parquet").is_file()
    assert (plan_dir / "locator_groups.parquet").is_file()
    assert (plan_dir / "reserve_targets.parquet").is_file()
    assert (plan_dir / "selection_report.json").is_file()
    assert not list(plan_dir.parent.glob(".staging-*"))


def test_plan_policy_scope_reuses_existing_bundle(catalog_fixture: Path) -> None:
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

    first = plan(
        catalog="cat123",
        scope="policy",
        selection_policy_path=pol_file,
    )
    plan_dir = (
        catalog_fixture
        / "manifests"
        / "filing_extraction"
        / "target_plans"
        / first["plan_id"]
    )
    marker = plan_dir / "reuse_marker.txt"
    marker.write_text("untouched", encoding="utf-8")

    second = plan(
        catalog="cat123",
        scope="policy",
        selection_policy_path=pol_file,
    )

    assert second["plan_id"] == first["plan_id"]
    assert second["plan_fingerprint"] == first["plan_fingerprint"]
    assert marker.is_file()


def test_plan_rejects_invalid_scope(catalog_fixture: Path) -> None:
    with pytest.raises(ValueError, match="scope must be"):
        plan(
            catalog="cat123",
            scope="fixture",
            forms=("10-K",),
        )


def test_expand_policy_plan_preserves_parent_selection(catalog_fixture: Path) -> None:
    policy = SelectionPolicy(
        corpus_id="test_corpus",
        forms=["10-K"],
        era_bands=[
            EraBand(name="era_2021", start_year=2021, end_year=2022),
            EraBand(name="era_2022", start_year=2022, end_year=2023),
            EraBand(name="era_2023", start_year=2023, end_year=2024),
        ],
        base_content_units=2,
        reserve_size=0,
    )
    pol_file = catalog_fixture / "policy.json"
    policy.write(pol_file)
    parent = plan(
        catalog="cat123",
        scope="policy",
        selection_policy_path=pol_file,
    )
    parent_dir = (
        catalog_fixture
        / "manifests"
        / "filing_extraction"
        / "target_plans"
        / parent["plan_id"]
    )

    child = expand(parent_dir, 3, selection_policy_path=pol_file)
    child_dir = parent_dir.parent / child["plan_id"]
    parent_keys = plan_expansion.plan_locator_keys(parent_dir)
    child_keys = plan_expansion.plan_locator_keys(child_dir)

    assert child["parent_plan_id"] == parent["plan_id"]
    assert child["target_units"] == 3
    assert child["added_locators_count"] == 1
    assert set(parent_keys).issubset(child_keys)
    assert len(set(child_keys)) == 3
    assert child["selection_policy"]["base_content_units"] == 3
