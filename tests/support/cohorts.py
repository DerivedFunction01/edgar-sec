"""Fixture cohort compilation: fixtures compiled as shared cohorts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.infra.storage.cohort.paths import resolve_cohort_paths
from edgar_sec.pipelines.cohort.ingestion import ingest_file_to_cohort
from edgar_sec.pipelines.cohort.sources import SOURCE_URLS, refresh_official_source
from edgar_sec.pipelines.metadata_sync.core.roster import (
    Roster,
    cohort_record_to_roster,
)
from tests.support.fixtures import fixture_path
from tests.support.http import FakeSession, build_test_http
from tests.support.scratch import scratch_root


@dataclass(frozen=True, slots=True)
class FixtureCohort:
    cohort_id: str
    row_count: int
    roster: Roster
    dataset: Path
    input_name: str
    input_path: Path
    input_fingerprint: str
    selected_limit: int | None
    rejected_row_count: int
    duplicate_row_count: int
    dataset_sha256: str


def _compile_fixture_cohort(
    fixture_name: str, root: str | Path, *, limit: int | None = None
) -> FixtureCohort:
    source = fixture_path(fixture_name).resolve()
    paths = resolve_cohort_paths(root)
    catalog = CohortCatalog(paths)
    result = ingest_file_to_cohort(source, catalog=catalog, paths=paths, limit=limit)
    record = result.cohort
    dataset = paths.resolve_relative_path(record.dataset_path)
    return FixtureCohort(
        cohort_id=record.cohort_id,
        row_count=record.row_count,
        roster=cohort_record_to_roster(record, paths),
        dataset=dataset,
        input_name=source.name,
        input_path=source,
        input_fingerprint=file_sha256(source),
        selected_limit=limit,
        rejected_row_count=result.quality.rejected_rows,
        duplicate_row_count=result.quality.duplicate_rows,
        dataset_sha256=record.dataset_sha256,
    )


def fixture_cohort(fixture_name: str, *, limit: int | None = None) -> FixtureCohort:
    """Compile a fixture as a temporary shared cohort and metadata roster."""
    return _compile_fixture_cohort(fixture_name, scratch_root(), limit=limit)


def fixture_ciks(fixture_name: str) -> tuple[str, ...]:
    """The usable CIKs of a committed fixture, in cohort order."""
    cohort = fixture_cohort(fixture_name)
    return cohort.roster.range_ciks(0, cohort.row_count)


def compiled_cohort(
    fixture_name: str, root: str | Path, *, limit: int | None = None
) -> FixtureCohort:
    """Compile a fixture under the caller's accepted storage root."""
    return _compile_fixture_cohort(fixture_name, root, limit=limit)


def published_universe(
    root: str | Path, fixture_name: str = "cik_lookup_universe_mini.txt"
) -> Path:
    """Publish and compile a registrant universe under ``root``; return its dataset.

    Goes through the real publish and compile path, on the committed mini fixture.
    """
    session = FakeSession()
    session.register_bytes(
        SOURCE_URLS["cik_lookup"], fixture_path(fixture_name).read_bytes()
    )
    paths = resolve_cohort_paths(root)
    catalog = CohortCatalog(paths)
    record = refresh_official_source(
        "cik_lookup", client=build_test_http(session), paths=paths, catalog=catalog
    )
    return paths.resolve_relative_path(record.dataset_path)


__all__ = [
    "FixtureCohort",
    "compiled_cohort",
    "fixture_ciks",
    "fixture_cohort",
    "published_universe",
]
