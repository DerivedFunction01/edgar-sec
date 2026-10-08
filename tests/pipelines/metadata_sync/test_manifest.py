"""Curated CIK files enter metadata_sync through shared cohort ingestion."""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.infra.storage.cohort.paths import resolve_cohort_paths
from edgar_sec.pipelines.metadata_sync.cohort_adapter import cohort_record_to_roster
from edgar_sec.pipelines.metadata_sync.manifest import (
    compile_cik_cohort,
    count_cohort_rows,
)
from edgar_sec.pipelines.metadata_sync.paths import resolve_metadata_paths
from tests.support import fixture_path


def _paths(root: Path):
    return resolve_metadata_paths(root)


def test_curated_file_registers_a_shared_canonical_cohort(tmp_path: Path) -> None:
    source = fixture_path("cik_sec_mini.csv")
    metadata = _paths(tmp_path)

    compiled = compile_cik_cohort(source, metadata_paths=metadata)

    shared_paths = resolve_cohort_paths(tmp_path)
    records = CohortCatalog(shared_paths).list_cohorts(tag="metadata_sync")
    assert len(records) == 1
    record = records[0]
    roster = cohort_record_to_roster(record, shared_paths)
    assert compiled.row_count == record.row_count == 4
    assert compiled.roster.roster_id == roster.roster_id
    assert compiled.input_fingerprint == file_sha256(source)
    assert compiled.dataset_sha256 == record.dataset_sha256
    assert compiled.duplicate_row_count == 1
    assert compiled.rejected_row_count == 3


def test_reingesting_an_unchanged_file_reuses_the_shared_record(
    tmp_path: Path,
) -> None:
    metadata = _paths(tmp_path)
    source = fixture_path("cik_sec_mini.csv")
    first = compile_cik_cohort(source, metadata_paths=metadata)
    second = compile_cik_cohort(source, metadata_paths=metadata)

    assert second.roster.roster_id == first.roster.roster_id
    assert second.roster.dataset == first.roster.dataset
    records = CohortCatalog(resolve_cohort_paths(tmp_path)).list_cohorts(
        tag="metadata_sync"
    )
    assert len(records) == 1


def test_limit_is_registered_as_a_distinct_selected_cohort(tmp_path: Path) -> None:
    source = fixture_path("cik_sec_mini.csv")
    metadata = _paths(tmp_path)
    full = compile_cik_cohort(source, metadata_paths=metadata)
    limited = compile_cik_cohort(source, limit=2, metadata_paths=metadata)

    assert limited.row_count == 2
    assert limited.roster.roster_id != full.roster.roster_id
    assert limited.input_fingerprint == full.input_fingerprint
    assert limited.selected_limit == 2


def test_limit_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="limit"):
        compile_cik_cohort(
            fixture_path("cik_sec_mini.csv"), limit=0, metadata_paths=_paths(tmp_path)
        )


def test_candidate_counting_does_not_register_a_cohort(tmp_path: Path) -> None:
    source = fixture_path("cik_sec_mini.csv")
    assert count_cohort_rows(source) == 4
    assert CohortCatalog(resolve_cohort_paths(tmp_path)).list_cohorts() == []


def test_missing_and_empty_inputs_fail_closed(tmp_path: Path) -> None:
    metadata = _paths(tmp_path)
    with pytest.raises(FileNotFoundError):
        compile_cik_cohort(tmp_path / "absent.csv", metadata_paths=metadata)
    empty = tmp_path / "empty.csv"
    empty.write_text("cik,name\nabc,not a CIK\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no usable CIKs"):
        compile_cik_cohort(empty, metadata_paths=metadata)
    assert (
        CohortCatalog(resolve_cohort_paths(tmp_path)).list_cohorts(tag="metadata_sync")
        == []
    )
