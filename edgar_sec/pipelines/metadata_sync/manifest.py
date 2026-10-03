"""CIK input compilation: a curated CSV becomes a content-addressed cohort.
The source digest is the reproducibility root, recorded in the plan, every row,
and the snapshot manifest. Normalization through zero-padding happens in one
DuckDB statement, so the input never reaches the Python heap.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.duckdb import connect, copy_query_to_parquet
from edgar_sec.infra.storage.parquet import count_parquet_rows

from .paths import (
    COMPILED_ROSTER_MANIFEST_KIND,
    MetadataPaths,
    resolve_metadata_paths,
)
from .roster import Roster, RosterError, read_roster

MAX_CIK_VALUE = 9_999_999_999

__all__ = [
    "MAX_CIK_VALUE",
    "CompiledCohort",
    "cik_cohort_key",
    "compile_cik_cohort",
    "count_cohort_rows",
]

#: One pass over the input: normalize, validate, deduplicate, number, pad.
#:
#: The reader is fully specified and never auto-detected. Auto-detection types the
#: CIK column as an integer -- discarding padding a curated file may already carry --
#: and collapses the columns of a ragged file into one field per line.
#:
#: ``c0`` is validated as text before it becomes an integer, because a bare cast
#: accepts more than a CIK: ``12.5`` is 13, ``1e5`` is 100000, ``0x10`` is 16. Each
#: names a real registrant, so an unguarded cast would invent cohort members.
#:
#: ``rn`` is first-appearance order, fixing both which duplicate row is kept and the
#: ordinal that defines chunk membership. Duplicates partition by CIK *value*, not
#: text -- ``1985`` and ``0000001985`` are one registrant written twice -- and the
#: ordering is stable across thread counts, so cohort identity does not depend on
#: the machine that compiled it.
_CIK_COHORT_QUERY = """
WITH raw AS (
    SELECT
        coalesce(c0, '') AS cik_text,
        coalesce(c1, '') AS name,
        row_number() OVER () AS rn
    FROM read_csv(
        ?,
        auto_detect = false,
        header = false,
        columns = {'c0': 'VARCHAR', 'c1': 'VARCHAR'},
        null_padding = true,
        all_varchar = true,
        strict_mode = false
    )
),
usable AS (
    SELECT rn, trim(cik_text) AS cik, trim(name) AS name
    FROM raw
    WHERE NOT (rn = 1 AND trim(cik_text) !~ '^[0-9]+$')
      AND trim(cik_text) <> ''
      AND trim(cik_text) ~ '^[0-9]+$'
      AND try_cast(trim(cik_text) AS BIGINT) BETWEEN 1 AND 9999999999
),
first_occurrence AS (
    SELECT rn, try_cast(cik AS BIGINT) AS cik_value, name
    FROM usable
    QUALIFY row_number() OVER (
        PARTITION BY try_cast(cik AS BIGINT) ORDER BY rn
    ) = 1
),
numbered AS (
    SELECT row_number() OVER (ORDER BY rn) - 1 AS ordinal, cik_value, name
    FROM first_occurrence
)
SELECT
    ordinal,
    printf('%010d', cik_value) AS cik_padded,
    name
FROM numbered
WHERE ? < 0 OR ordinal < ?
ORDER BY ordinal
"""

#: The same pass, counted rather than written, so the cohort manifest reports what
#: the input contained and not only what survived; one scan classifies every row.
_CIK_COHORT_QUALITY_QUERY = """
WITH raw AS (
    SELECT
        coalesce(c0, '') AS cik_text,
        coalesce(c1, '') AS name_text,
        row_number() OVER () AS rn
    FROM read_csv(
        ?,
        auto_detect = false,
        header = false,
        columns = {'c0': 'VARCHAR', 'c1': 'VARCHAR'},
        null_padding = true,
        all_varchar = true,
        strict_mode = false
    )
),
classified AS (
    SELECT
        (rn = 1 AND trim(cik_text) !~ '^[0-9]+$') AS is_header,
        (trim(cik_text) = '' AND trim(name_text) = '') AS is_blank,
        (
            trim(cik_text) <> ''
            AND trim(cik_text) ~ '^[0-9]+$'
            AND try_cast(trim(cik_text) AS BIGINT) BETWEEN 1 AND 9999999999
        ) AS is_valid,
        trim(cik_text) AS cik
    FROM raw
)
SELECT
    count(*) FILTER (
        WHERE NOT is_header AND NOT is_blank AND NOT is_valid
    ) AS rejected_rows,
    count(*) FILTER (WHERE is_valid) - count(DISTINCT try_cast(cik AS BIGINT)) FILTER (
        WHERE is_valid
    ) AS duplicate_rows
FROM classified
"""

#: A bare count for listing a candidate input. Counts distinct CIK *values*, not
#: texts: ``1985`` and ``0000001985`` are one registrant and the cohort keeps one.
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


def cik_cohort_key(input_fingerprint: str, limit: int | None = None) -> str:
    """Name the compiled cohort for one source digest and optional limit.
    The limit is part of the key: a bounded cohort must not share a directory.
    """
    if limit is None:
        return input_fingerprint
    return f"{input_fingerprint}-limit-{int(limit)}"


def compile_cik_cohort(
    input_path: str | os.PathLike[str],
    *,
    limit: int | None = None,
    metadata_paths: MetadataPaths | None = None,
) -> CompiledCohort:
    """Compile a CIK CSV into a content-addressed cohort dataset.
    Keyed by the source digest, so an unchanged input reuses its dataset. A missing
    input fails loudly rather than yielding a plan over an empty cohort.
    """
    source = Path(input_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"input manifest not found: {source}")
    if limit is not None and limit < 1:
        raise ValueError(f"a cohort limit must be >= 1, got {limit}")

    fingerprint = file_sha256(source)
    key = cik_cohort_key(fingerprint, limit)
    paths = metadata_paths or resolve_metadata_paths()
    dataset = paths.compiled_cohort_file(key)
    manifest_path = paths.compiled_cohort_manifest(key)

    reused = _reuse_compiled(manifest_path, dataset, fingerprint, limit)
    if reused is not None:
        return reused

    bounded = -1 if limit is None else int(limit)
    con = connect()
    try:
        row_count = copy_query_to_parquet(
            con,
            _CIK_COHORT_QUERY,
            dataset,
            params=[str(source), str(bounded), str(bounded)],
        )
        rejected, duplicates = con.execute(
            _CIK_COHORT_QUALITY_QUERY, [str(source)]
        ).fetchone()
    finally:
        con.close()

    if not row_count:
        raise ValueError(f"input manifest contains no usable CIKs: {source}")

    roster = read_roster(dataset)
    cohort = CompiledCohort(
        roster=roster,
        input_name=source.name,
        input_path=source,
        input_fingerprint=fingerprint,
        selected_limit=limit,
        rejected_row_count=int(rejected or 0),
        duplicate_row_count=int(duplicates or 0),
        dataset_sha256=file_sha256(dataset),
    )
    _write_manifest(manifest_path, cohort)
    return cohort


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


def _reuse_compiled(
    manifest_path: Path,
    dataset: Path,
    fingerprint: str,
    limit: int | None,
) -> CompiledCohort | None:
    """Return a previously compiled cohort when it still matches the input."""
    if not manifest_path.is_file() or not dataset.is_file():
        return None
    try:
        recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(recorded, dict):
        return None
    if recorded.get("manifest_kind") != COMPILED_ROSTER_MANIFEST_KIND:
        return None
    if recorded.get("input_fingerprint") != fingerprint:
        return None
    if recorded.get("selected_limit") != limit:
        return None

    expected_digest = str(recorded.get("dataset_sha256", ""))
    if not expected_digest or file_sha256(dataset) != expected_digest:
        return None

    try:
        roster = read_roster(dataset, expected_roster_id=str(recorded.get("roster_id")))
    except (FileNotFoundError, RosterError):
        return None
    return CompiledCohort(
        roster=roster,
        input_name=str(recorded.get("input_name", dataset.name)),
        input_path=Path(str(recorded.get("input_path", dataset.name))),
        input_fingerprint=fingerprint,
        selected_limit=limit,
        rejected_row_count=int(recorded.get("rejected_row_count") or 0),
        duplicate_row_count=int(recorded.get("duplicate_row_count") or 0),
        dataset_sha256=expected_digest,
    )


def _write_manifest(manifest_path: Path, cohort: CompiledCohort) -> None:
    """Record what a compiled cohort resolved to, so a rerun can trust it."""
    atomic_write_json(
        manifest_path,
        {
            "manifest_kind": COMPILED_ROSTER_MANIFEST_KIND,
            "roster_id": cohort.roster_id,
            "row_count": cohort.row_count,
            "input_name": cohort.input_name,
            "input_path": str(cohort.input_path),
            "input_fingerprint": cohort.input_fingerprint,
            "selected_limit": cohort.selected_limit,
            "rejected_row_count": cohort.rejected_row_count,
            "duplicate_row_count": cohort.duplicate_row_count,
            "dataset_sha256": cohort.dataset_sha256,
            "cohort_rows": count_parquet_rows(cohort.roster.dataset)
            if cohort.roster.dataset is not None
            else 0,
        },
    )
