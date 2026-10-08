"""Resolve the active SEC registrant cohort for metadata planning."""

from __future__ import annotations

import json

from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.infra.storage.cohort.paths import resolve_cohort_paths
from edgar_sec.infra.storage.cohort.operations import sample_cohort
from edgar_sec.infra.storage.cohort.sources import resolve_active_source

from .cohort_adapter import cohort_record_to_roster
from .paths import MetadataPaths
from .roster import Roster, RosterError, read_roster

__all__ = ["compile_universe_cohort"]


def compile_universe_cohort(
    metadata_paths: MetadataPaths,
    *,
    source_snapshot_id: str,
    limit: int | None = None,
) -> Roster:
    """Resolve the active source cohort, optionally retaining its lowest CIKs."""
    if limit is not None and limit < 1:
        raise RosterError(f"a cohort limit must be >= 1, got {limit}")
    paths = resolve_cohort_paths(metadata_paths.artifacts_root)
    catalog = CohortCatalog(paths)
    record = resolve_active_source("cik_lookup", catalog=catalog)
    if record is None:
        raise FileNotFoundError("no active cik_lookup cohort is published")
    origin = json.loads(record.origin_json)
    active_id = str(origin.get("source_snapshot_id", record.cohort_id))
    if source_snapshot_id not in {active_id, record.cohort_id}:
        raise FileNotFoundError(
            f"cik_lookup source {source_snapshot_id!r} is not the active source"
        )

    roster = cohort_record_to_roster(record, paths)
    if limit is None or limit >= roster.row_count:
        return roster

    output = (
        metadata_paths.transient_dir(f"universe-{record.cohort_id}-limit-{limit}")
        / "ciks.parquet"
    )
    rows = sample_cohort(roster.dataset, output, sample_limit=limit)
    selected = read_roster(output)
    if rows != selected.row_count or selected.row_count != limit:
        raise RosterError("limited universe cohort has an unexpected row count")
    return selected
