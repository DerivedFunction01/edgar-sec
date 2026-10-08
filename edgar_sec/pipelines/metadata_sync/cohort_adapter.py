"""Adapters between the shared cohort catalog and metadata roster handles."""

from __future__ import annotations

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.cohort.models import CohortRecord
from edgar_sec.infra.storage.cohort.paths import CohortPaths

from .roster import Roster, RosterError, read_roster


def cohort_record_to_roster(record: CohortRecord, paths: CohortPaths) -> Roster:
    dataset = paths.resolve_relative_path(record.dataset_path)
    if not dataset.is_file() or file_sha256(dataset) != record.dataset_sha256:
        raise RosterError(
            f"cohort {record.cohort_id!r} dataset is missing or its digest does not match"
        )
    roster = read_roster(dataset)
    if (
        roster.row_count != record.row_count
        or record.row_count != record.distinct_cik_count
    ):
        raise RosterError(
            f"cohort {record.cohort_id!r} row count does not match its catalog record"
        )
    return roster


__all__ = ["cohort_record_to_roster"]
