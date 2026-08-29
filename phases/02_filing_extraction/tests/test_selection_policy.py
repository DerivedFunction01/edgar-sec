"""Unit tests for Phase 02 selection policy and seed CIK parsing."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

selection_policy = importlib.import_module(
    "phases.02_filing_extraction.core.selection_policy"
)
EraBand = selection_policy.EraBand
SeedFiler = selection_policy.SeedFiler
SelectionPolicy = selection_policy.SelectionPolicy
compute_seed_fingerprint = selection_policy.compute_seed_fingerprint
load_seed_cik_csv = selection_policy.load_seed_cik_csv


def test_era_band_matching() -> None:
    band_1 = EraBand(name="era_early", start_year=1995, end_year=2005)
    assert band_1.matches(1995, "1995-03-15")
    assert band_1.matches(2000, "2000-12-31")
    assert not band_1.matches(2005, "2005-01-01")
    assert not band_1.matches(1990, "1990-05-20")

    band_date = EraBand(
        name="era_sec_rule", start_date="2020-06-15", end_date="2024-01-01"
    )
    assert band_date.matches(2020, "2020-06-15")
    assert band_date.matches(2022, "2022-01-01")
    assert not band_date.matches(2020, "2020-06-14")
    assert not band_date.matches(2024, "2024-01-01")


def test_era_band_requires_at_least_one_bound() -> None:
    with pytest.raises(ValueError, match="must specify at least one boundary"):
        EraBand(name="invalid_band")


def test_selection_policy_validation_and_fingerprinting() -> None:
    policy = SelectionPolicy(
        corpus_id="custom_corpus",
        forms=["10-K", "20-F"],
        era_bands=[
            EraBand(name="band_1", start_year=2000, end_year=2010),
            EraBand(name="band_2", start_year=2010, end_year=2020),
        ],
        base_content_units=300,
        floors={"form": {"10-K": 50, "20-F": 20}},
        weights={"form": 1.0, "era": 1.5},
        caps={"form": 0.8},
    )

    data = policy.to_dict()
    assert data["corpus_id"] == "custom_corpus"
    assert len(data["era_bands"]) == 2
    assert len(policy.policy_fingerprint) == 32

    roundtrip = SelectionPolicy.from_dict(data)
    assert roundtrip.corpus_id == policy.corpus_id
    assert len(roundtrip.era_bands) == 2
    assert roundtrip.era_bands[0].name == "band_1"
    assert roundtrip.policy_fingerprint == policy.policy_fingerprint


def test_selection_policy_rejects_unknown_dimensions() -> None:
    with pytest.raises(ValueError, match="unknown policy dimensions"):
        SelectionPolicy(
            corpus_id="bad",
            forms=["10-K"],
            floors={"non_existent_dim": {"val": 10}},
        )


def test_load_seed_cik_csv_normalizes_and_validates(tmp_path: Path) -> None:
    csv_file = tmp_path / "seed-cik.csv"
    csv_file.write_text(
        "cik,seed_group,coverage_tags,notes\n"
        "37996,automotive,large-filer,Ford\n"
        "0000078003,healthcare,pharma,Historical\n",
        encoding="utf-8",
    )

    seed_map = load_seed_cik_csv(csv_file)
    assert "0000037996" in seed_map
    assert "0000078003" in seed_map
    assert seed_map["0000037996"].seed_group == "automotive"
    assert seed_map["0000078003"].notes == "Historical"

    fp = compute_seed_fingerprint(seed_map)
    assert len(fp) == 32


def test_load_seed_cik_csv_rejects_duplicates(tmp_path: Path) -> None:
    csv_file = tmp_path / "seed-cik.csv"
    csv_file.write_text(
        "cik,seed_group\n0000037996,group1\n37996,group2\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate CIK"):
        load_seed_cik_csv(csv_file)
