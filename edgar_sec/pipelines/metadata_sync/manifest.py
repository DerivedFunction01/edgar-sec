"""Register curated CIK CSV inputs in the shared cohort catalog."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.cohort.catalog import CohortCatalog
from edgar_sec.infra.storage.cohort.ingestion import ingest_file_to_cohort
from edgar_sec.infra.storage.cohort.paths import resolve_cohort_paths
from edgar_sec.infra.storage.duckdb import connect

from .cohort_adapter import cohort_record_to_roster
from .paths import MetadataPaths, resolve_metadata_paths
from .roster import Roster

MAX_CIK_VALUE = 9_999_999_999

__all__ = ["MAX_CIK_VALUE", "CompiledCohort", "compile_cik_cohort", "count_cohort_rows"]

#: Counts distinct CIK values without registering a cohort.
_CIK_COUNT_QUERY = """
SELECT count(DISTINCT try_cast(cik_text AS BIGINT))
FROM (
    SELECT coalesce(c0, '') AS cik_text, row_number() OVER () AS rn
    FROM read_csv(
        ?,
        auto_detect = false,
        header = false,
        columns = {'c0': 'VARCHAR', 'c1': 'VARCHAR'},
        null_padding = true,
        all_varchar = true,
        strict_mode = false
    )
)
WHERE NOT (rn = 1 AND trim(cik_text) !~ '^[0-9]+$')
  AND trim(cik_text) <> ''
  AND trim(cik_text) ~ '^[0-9]+$'
  AND try_cast(trim(cik_text) AS BIGINT) BETWEEN 1 AND 9999999999
"""


@dataclass(frozen=True, slots=True)
class CompiledCohort:
    """A cohort resolved from one CIK input file, and what it took to get there."""

    roster: Roster
    input_name: str
    input_path: Path
    input_fingerprint: str
    selected_limit: int | None = None
    rejected_row_count: int = 0
    duplicate_row_count: int = 0
    dataset_sha256: str = ""

    @property
    def roster_id(self) -> str:
        """Identity of the cohort this input resolved to."""
        return self.roster.roster_id

    @property
    def row_count(self) -> int:
        """Number of CIKs in the compiled cohort."""
        return self.roster.row_count


def compile_cik_cohort(
    input_path: str | os.PathLike[str],
    *,
    limit: int | None = None,
    metadata_paths: MetadataPaths | None = None,
) -> CompiledCohort:
    """Register a CIK CSV and return its verified metadata roster handle."""
    source = Path(input_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"input manifest not found: {source}")
    if limit is not None and limit < 1:
        raise ValueError(f"a cohort limit must be >= 1, got {limit}")
    if count_cohort_rows(source) == 0:
        raise ValueError(f"input manifest contains no usable CIKs: {source}")

    fingerprint = file_sha256(source)
    cohort_paths = resolve_cohort_paths(
        (metadata_paths or resolve_metadata_paths()).artifacts_root
    )
    catalog = CohortCatalog(cohort_paths)
    result = ingest_file_to_cohort(
        source,
        catalog=catalog,
        paths=cohort_paths,
        limit=limit,
        description="CIK roster imported by metadata_sync",
        tags=("metadata_sync",),
    )
    if result.cohort.row_count == 0:
        raise ValueError(f"input manifest contains no usable CIKs: {source}")
    roster = cohort_record_to_roster(result.cohort, cohort_paths)
    return CompiledCohort(
        roster=roster,
        input_name=source.name,
        input_path=source,
        input_fingerprint=fingerprint,
        selected_limit=limit,
        rejected_row_count=result.quality.rejected_rows,
        duplicate_row_count=result.quality.duplicate_rows,
        dataset_sha256=result.cohort.dataset_sha256,
    )


def count_cohort_rows(input_path: str | os.PathLike[str]) -> int:
    """Count the usable CIKs in an input without compiling it.
    Nothing is written and no identity is derived.
    """
    source = Path(input_path)
    if not source.is_file():
        return 0
    con = connect()
    try:
        return int(con.execute(_CIK_COUNT_QUERY, [str(source.resolve())]).fetchone()[0])
    finally:
        con.close()
