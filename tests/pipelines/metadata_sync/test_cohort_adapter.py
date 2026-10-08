"""Metadata roster handles verify shared cohort identity and file bytes."""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.infra.storage.cohort.ingestion import ingest_file_to_cohort
from edgar_sec.infra.storage.cohort.models import CohortRecord
from edgar_sec.infra.storage.cohort.paths import CohortPaths, resolve_cohort_paths
from edgar_sec.pipelines.metadata_sync.cohort_adapter import cohort_record_to_roster
from edgar_sec.pipelines.metadata_sync.roster import RosterError
from tests.support import fixture_path


def _ingest(paths: CohortPaths) -> CohortRecord:
    return ingest_file_to_cohort(
        fixture_path("cik_sec_mini.csv"),
        catalog=CohortCatalog(paths),
        paths=paths,
        tags=("metadata_sync",),
    ).cohort


def test_adapter_loads_a_verified_shared_record(tmp_path: Path) -> None:
    paths = resolve_cohort_paths(tmp_path)
    record = _ingest(paths)

    roster = cohort_record_to_roster(record, paths)

    assert roster.row_count == record.row_count
    assert roster.dataset is not None
    assert roster.roster_id != record.roster_id


def test_adapter_rejects_a_dataset_digest_mismatch(tmp_path: Path) -> None:
    paths = resolve_cohort_paths(tmp_path)
    record = _ingest(paths)
    dataset = paths.resolve_relative_path(record.dataset_path)
    dataset.write_bytes(b"tampered")

    with pytest.raises(RosterError, match="digest does not match"):
        cohort_record_to_roster(record, paths)
