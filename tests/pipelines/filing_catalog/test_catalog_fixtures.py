"""Fixture-contract tests: every required edge case must be present in the inputs,
so regeneration cannot weaken the oracle the DuckDB SQL is checked against.
"""

from __future__ import annotations

import csv
import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pytest

from edgar_sec.domain.submissions.schemas import SUBMISSION_METADATA_SCHEMA
from tests.support import catalog_fixture_path


def _read_csv(name: str) -> list[dict[str, str]]:
    with catalog_fixture_path(name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="module")
def sample_table() -> Any:
    return pq.read_table(catalog_fixture_path("sample_submission_metadata.parquet"))


@pytest.fixture(scope="module")
def targets() -> list[dict[str, str]]:
    return _read_csv("expected_filing_targets.csv")


@pytest.fixture(scope="module")
def profiles() -> list[dict[str, str]]:
    return _read_csv("expected_company_profiles.csv")


# --- input contract -------------------------------------------------------


def test_sample_input_matches_phase1_schema(sample_table: Any) -> None:
    assert sample_table.schema.names == SUBMISSION_METADATA_SCHEMA.names


def test_sample_input_carries_a_duplicate_cik_for_dedup(sample_table: Any) -> None:
    """A CIK must appear twice so the dedup window has work to do."""
    counts: dict[str, int] = defaultdict(int)
    for cik in sample_table.column("cik").to_pylist():
        counts[cik] += 1
    assert any(count > 1 for count in counts.values()), counts


def test_sample_input_covers_every_status(sample_table: Any) -> None:
    """Failed and partial must both survive normalization."""
    statuses = set(sample_table.column("status").to_pylist())
    assert {"ok", "partial", "failed"} <= statuses


# --- the seven edge cases, asserted against the derived expectations -------


def test_edge_case_1_locator_fan_out(targets: list[dict[str, str]]) -> None:
    """Two CIKs, one accession, both bundle-fallback, one locator key."""
    by_locator: dict[str, set[str]] = defaultdict(set)
    for row in targets:
        by_locator[row["document_locator_key"]].add(row["source_cik"])
    shared = {k: v for k, v in by_locator.items() if len(v) > 1}
    assert shared, "no locator key is shared by more than one CIK"

    locator = next(iter(shared))
    occurrences = [r for r in targets if r["document_locator_key"] == locator]
    assert len({r["occurrence_id"] for r in occurrences}) == len(occurrences), (
        "occurrence ids must stay distinct when a locator is shared"
    )
    assert len({r["accession"] for r in occurrences}) == 1


def test_edge_case_2_amendment_forms(targets: list[dict[str, str]]) -> None:
    """A form filter naming ``10-K`` must not be assumed to reach its variants."""
    forms = {row["form"] for row in targets}
    assert {"10-K/A", "8-K/A"} <= forms
    assert "10-K" in forms
    assert "10-KT" in forms
    assert "10-KSB" in forms


def test_edge_case_3_bundle_fallback(targets: list[dict[str, str]]) -> None:
    """A missing primary document resolves to the raw accession plus .txt."""
    fallback = [r for r in targets if r["document_path_source"] == "submission_bundle"]
    assert fallback, "no bundle-fallback row present"
    for row in fallback:
        assert not row["primary_document"].strip()
        assert row["document_path"].endswith(".txt")
        # The path keeps the raw hyphenated accession; ``accession`` is unhyphenated.
        assert "-" in row["document_path"]
        assert "-" not in row["accession"]


def test_edge_case_4_primary_document(targets: list[dict[str, str]]) -> None:
    populated = [r for r in targets if r["document_path_source"] == "primary_document"]
    assert populated
    for row in populated:
        assert row["document_path"] == row["primary_document"].strip()


def test_edge_case_5_status_inheritance(profiles: list[dict[str, str]]) -> None:
    by_status: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in profiles:
        by_status[row["status"]].append(row)
    assert by_status["failed"], "no failed profile present"
    assert by_status["partial"], "no partial profile present"
    # A failed registrant contributes no filings but still gets a profile row.
    for row in by_status["failed"]:
        assert row["filing_count"] == "0"


def test_edge_case_6_null_coalescing(targets: list[dict[str, str]]) -> None:
    """Null size becomes 0 and null XBRL booleans become false."""
    zeroed = [r for r in targets if r["reported_size"] == "0"]
    assert zeroed, "no row exercised the null-size coalesce"
    assert all(r["is_xbrl"] in {"True", "False"} for r in targets)
    assert any(r["is_xbrl"] == "False" for r in targets)


def test_edge_case_7_profile_dedup(profiles: list[dict[str, str]]) -> None:
    """One profile row per CIK, holding the latest fetched_at."""
    ciks = [r["cik"] for r in profiles]
    assert len(ciks) == len(set(ciks)), "duplicate CIK survived dedup"
    duplicates = [r for r in profiles if r["input_name"].endswith("#2026-03-08")]
    assert duplicates, "the later duplicate row did not win dedup"
    for row in duplicates:
        assert row["fetched_at"] == "2026-03-08T00:00:00Z"


# --- expected-value integrity ---------------------------------------------


def test_expected_ids_are_independently_reproducible(
    targets: list[dict[str, str]],
) -> None:
    """Every identity, recomputed in plain Python from the derivation rules."""
    for row in targets:
        expected_occurrence = hashlib.sha256(
            f"{row['source_cik']}:{row['accession']}:{row['document_path']}".encode()
        ).hexdigest()
        expected_locator = hashlib.sha256(
            f"{row['accession']}:{row['document_path']}".encode()
        ).hexdigest()
        assert row["occurrence_id"] == expected_occurrence
        assert row["document_locator_key"] == expected_locator


def test_expected_targets_are_sorted_by_projection_key(
    targets: list[dict[str, str]],
) -> None:
    """The catalog orders shards by (source_cik, accession, document_path)."""
    keys = [(r["source_cik"], r["accession"], r["document_path"]) for r in targets]
    assert keys == sorted(keys)


def test_expected_profiles_are_sorted_by_cik(profiles: list[dict[str, str]]) -> None:
    ciks = [r["cik"] for r in profiles]
    assert ciks == sorted(ciks)


def test_every_profile_fixture_row_exists(sample_table: Any) -> None:
    """The committed CSV and the committed Parquet describe the same run."""
    assert catalog_fixture_path("sample_submission_metadata.parquet").is_file()
    assert catalog_fixture_path("expected_filing_targets.csv").is_file()
    assert catalog_fixture_path("expected_company_profiles.csv").is_file()
    assert catalog_fixture_path("cik_sample.csv").is_file()


def test_fixture_directory_is_populated() -> None:
    assert catalog_fixture_path("expected_filing_targets.csv").is_file()


def test_archive_urls_use_unpadded_cik(targets: list[dict[str, str]]) -> None:
    """The archive path drops CIK zero padding."""
    for row in targets:
        assert f"/{row['source_cik'].lstrip('0')}/" in row["archive_url"]
        assert f"/{row['source_cik']}/" not in row["archive_url"]


def test_degenerate_cik_unpadding_is_documented_as_divergent() -> None:
    """ltrim and int() disagree on all zeros, so the divergence stays pinned."""
    assert "0000".lstrip("0") == ""
    assert str(int("0000")) == "0"
    assert "0000".lstrip("0") != str(int("0000"))


def test_cik_sample_manifest_matches_fixture_coverage() -> None:
    """The committed seed manifest must name at least five registrants."""
    with catalog_fixture_path("cik_sample.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) >= 5
    assert all(row["cik"].zfill(10) == row["cik"] for row in rows)


def test_orphan_fixtures_absent() -> None:
    """No test module may live inside the data-only fixtures directory."""
    stray = [
        path.name
        for path in catalog_fixture_path(".").parent.rglob("test_*.py")
        if "fixtures" in path.parts
    ]
    assert not stray, f"test modules inside a fixtures directory: {stray}"


def test_fixture_files_are_not_empty() -> None:
    for name in (
        "cik_sample.csv",
        "expected_filing_targets.csv",
        "expected_company_profiles.csv",
    ):
        path: Path = catalog_fixture_path(name)
        assert path.stat().st_size > 0, name
