"""Unit tests for Phase 02 selection features extraction and era calculation."""

from __future__ import annotations

import importlib
from pathlib import Path

from defs.storage import FinalizedArtifact, pa, write_table_atomic

selection_policy = importlib.import_module(
    "phases.02_filing_extraction.core.selection_policy"
)
selection_features = importlib.import_module(
    "phases.02_filing_extraction.core.selection_features"
)

EraBand = selection_policy.EraBand
SelectionPolicy = selection_policy.SelectionPolicy
FeatureSnapshotBuilder = selection_features.FeatureSnapshotBuilder
era_of = selection_features.era_of
form_family = selection_features.form_family


def test_form_family_normalization() -> None:
    assert form_family("10-K/A") == "10-K"
    assert form_family("10-K_A") == "10-K"
    assert form_family("20-F-POS") == "20-F"
    assert form_family("8-K/A") == "8-K"
    assert form_family("S-1_A") == "S-1"


def test_era_of_dynamic_matching() -> None:
    bands = [
        EraBand(name="pre_2000", end_year=2000),
        EraBand(name="2000_2010", start_year=2000, end_year=2011),
        EraBand(name="2011_plus", start_year=2011),
    ]

    assert era_of("1998-12-31", bands) == "pre_2000"
    assert era_of("2005-06-15", bands) == "2000_2010"
    assert era_of("2023-01-01", bands) == "2011_plus"
    assert era_of(None, bands) == "unknown"
    assert era_of("", bands) == "unknown"


def test_feature_snapshot_builder(tmp_path: Path) -> None:
    target_dir = tmp_path / "targets" / "form=10-K"
    target_dir.mkdir(parents=True)
    target_file = target_dir / "data.parquet"

    # Create synthetic target parquet
    data = {
        "occurrence_id": ["occ1", "occ2"],
        "document_locator_key": ["loc1", "loc2"],
        "source_cik": ["0000000001", "0000000002"],
        "accession": ["0000000001-23-000001", "0000000002-23-000001"],
        "form": ["10-K", "10-K"],
        "is_amendment": [False, False],
        "filing_date": ["2023-03-01", "2023-03-02"],
        "report_date": ["2022-12-31", "2022-12-31"],
        "primary_document": ["doc.htm", "doc.htm"],
        "document_path": ["data/1.htm", "data/2.htm"],
        "archive_url": ["http://sec.gov/1", "http://sec.gov/2"],
        "reported_size": [500000, 600000],
        "is_xbrl": [True, True],
        "is_inline_xbrl": [True, True],
        "is_xbrl_numeric": [True, True],
    }
    write_table_atomic(pa.Table.from_pydict(data), target_file)

    # Create synthetic profile parquet
    profile_file = tmp_path / "profiles.parquet"
    prof_data = {
        "cik": ["0000000001", "0000000002"],
        "sic": ["1000", "2000"],
        "sic_description": ["Mining", "Manufacturing"],
        "owner_org_cik": ["0000000001", None],
        "owner_org_name": ["Parent Co", None],
        "entity_type": ["operating", "operating"],
        "filer_category": ["Large Accelerated Filer", "Accelerated Filer"],
        "state_of_incorporation": ["DE", "NY"],
        "state_of_business": ["CA", "TX"],
        "foreign_country_code": [None, "CA"],
        "company_name": ["Co One", "Co Two"],
    }
    write_table_atomic(pa.Table.from_pydict(prof_data), profile_file)

    policy = SelectionPolicy(
        corpus_id="test_corpus",
        forms=["10-K"],
        era_bands=[EraBand(name="era_test", start_year=2020, end_year=2030)],
        base_content_units=10,
    )

    builder = FeatureSnapshotBuilder(
        target_root=tmp_path / "targets",
        profile_path=profile_file,
        output_root=tmp_path / "scratch",
        policy=policy,
    )
    snapshot = builder.build()

    assert snapshot.occurrence_features.is_file()
    assert snapshot.locator_features.is_file()
    assert snapshot.manifest.is_file()

    with FinalizedArtifact(snapshot.occurrence_features) as occ_artifact:
        assert occ_artifact.count() == 2
        rows = occ_artifact.run(f"SELECT era FROM {occ_artifact.relation}")
        assert [r[0] for r in rows] == ["era_test", "era_test"]
