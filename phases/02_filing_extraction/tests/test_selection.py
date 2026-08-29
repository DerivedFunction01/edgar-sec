"""Unit tests for Phase 02 deficit selector, floors, composites, and reserve pools."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from defs.storage import pa, write_table_atomic

selection_policy = importlib.import_module(
    "phases.02_filing_extraction.core.selection_policy"
)
selection_features = importlib.import_module(
    "phases.02_filing_extraction.core.selection_features"
)
selection = importlib.import_module("phases.02_filing_extraction.core.selection")

EraBand = selection_policy.EraBand
SeedFiler = selection_policy.SeedFiler
SelectionPolicy = selection_policy.SelectionPolicy
FeatureSnapshotBuilder = selection_features.FeatureSnapshotBuilder
DeficitSelector = selection.DeficitSelector


@pytest.fixture()
def snapshot_fixture(tmp_path: Path):
    target_dir = tmp_path / "targets" / "form=10-K"
    target_dir.mkdir(parents=True)
    target_file = target_dir / "data.parquet"

    # Create synthetic targets with 4 items across 2 CIKs
    data = {
        "occurrence_id": ["occ1", "occ2", "occ3", "occ4"],
        "document_locator_key": ["loc1", "loc2", "loc3", "loc4"],
        "source_cik": ["0000000001", "0000000001", "0000000002", "0000000003"],
        "accession": ["acc1", "acc2", "acc3", "acc4"],
        "form": ["10-K", "10-K", "10-K", "10-K"],
        "is_amendment": [False, False, False, False],
        "filing_date": ["2021-03-01", "2022-03-01", "2023-03-01", "2023-03-02"],
        "report_date": ["2020-12-31", "2021-12-31", "2022-12-31", "2022-12-31"],
        "primary_document": ["doc.htm", "doc.htm", "doc.htm", "doc.htm"],
        "document_path": ["data/1.htm", "data/2.htm", "data/3.htm", "data/4.htm"],
        "archive_url": [
            "http://sec.gov/1",
            "http://sec.gov/2",
            "http://sec.gov/3",
            "http://sec.gov/4",
        ],
        "reported_size": [100000, 200000, 300000, 400000],
        "is_xbrl": [True, True, True, True],
        "is_inline_xbrl": [True, True, True, True],
        "is_xbrl_numeric": [True, True, True, True],
    }
    write_table_atomic(pa.Table.from_pydict(data), target_file)

    profile_file = tmp_path / "profiles.parquet"
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

    policy = SelectionPolicy(
        corpus_id="test_corpus",
        forms=["10-K"],
        era_bands=[
            EraBand(name="era_2020", start_year=2020, end_year=2021),
            EraBand(name="era_2021", start_year=2021, end_year=2022),
            EraBand(name="era_2022", start_year=2022, end_year=2023),
        ],
        base_content_units=2,
        reserve_size=1,
        floors={"foreign_status": {"foreign": 1}},
    )

    builder = FeatureSnapshotBuilder(
        target_root=tmp_path / "targets",
        profile_path=profile_file,
        output_root=tmp_path / "scratch",
        policy=policy,
    )
    snapshot = builder.build()
    return snapshot, policy


def test_deficit_selector_satisfies_floors_and_reserves(snapshot_fixture) -> None:
    snapshot, policy = snapshot_fixture

    seed_filers = {
        "0000000001": SeedFiler(
            cik="0000000001", seed_group="test_group", notes="Seed Co"
        )
    }

    selector = DeficitSelector(
        snapshot_dir=snapshot.snapshot_dir,
        policy=policy,
        seed_filers=seed_filers,
    )

    result = selector.select()

    assert len(result.active_locators) == 2
    assert len(result.active_occurrences) == 2
    assert len(result.reserve_locators) == 1
    # Check disjointness
    assert set(result.active_locators).isdisjoint(set(result.reserve_locators))

    # Check report
    report = result.report
    assert report["active_locators_count"] == 2
    assert report["reserve_locators_count"] == 1
    assert "coverage_distributions" in report
