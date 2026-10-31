from __future__ import annotations

from pathlib import Path

from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.pipelines.cohort.ingestion import ingest_file_to_cohort
from edgar_sec.infra.storage.cohort.paths import CohortPaths, resolve_cohort_paths
from edgar_sec.infra.storage.cohort.models import CohortRecord
from edgar_sec.pipelines.metadata_sync.roster import Roster, cohort_record_to_roster


def publish_test_cohort(
    source: str | Path,
    artifacts_root: str | Path,
    *,
    limit: int | None = None,
    name: str | None = None,
) -> tuple[CohortRecord, CohortPaths, Roster]:
    paths = resolve_cohort_paths(artifacts_root)
    catalog = CohortCatalog(paths)
    record = ingest_file_to_cohort(
        source, catalog=catalog, paths=paths, limit=limit, name=name
    ).cohort
    return record, paths, cohort_record_to_roster(record, paths)
