"""CIK input compilation: a curated CSV becomes a content-addressed cohort.

The compiled cohort is the reproducibility root of a run. The source file's
SHA-256 digest is the ``input_fingerprint`` recorded in the plan, in every row,
and in the published snapshot manifest, and the cohort's own identity is derived
from the ordered CIKs and names it resolved to. Malformed rows are counted and
reported in the cohort manifest rather than silently dropped.

Normalization, validation, deduplication, ordinal assignment and zero-padding
all happen in one DuckDB statement, so a cohort of any size is produced without
the input passing through the Python heap. Padding is applied last, in the
projection that writes the column: the CIK is an integer for every operation
that has to reason about it, and a ten-character string only once it is stored.
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
#: The reader is fully specified and never auto-detects. Auto-detection reads a
#: 20,480-row sample, so it both types the CIK column as an integer -- which would
#: discard the zero-padding a curated file may already carry -- and hard-errors
#: on a non-numeric cell past the sample. Worse, on a ragged file it collapses the
#: columns and returns a whole line as a single field. The two shape flags keep the
#: reader positional and forgiving the way a two-column parser has to be:
#: ``null_padding`` yields a null name for a short row, and ``strict_mode=false``
#: drops the surplus fields of a long row instead of failing the whole ingest --
#: which is what taking the second column has always meant.
#:
#: ``c0`` is validated as text before it becomes an integer, because a cast alone
#: accepts far more than a CIK: ``12.5`` becomes 13, ``1e5`` becomes 100000, and
#: ``0x10`` becomes 16. Each of those is a real registrant, so an unguarded cast
#: would invent members of the cohort that pass every later check.
#:
#: ``rn`` is first-appearance order, which fixes both which row a duplicate keeps
#: and the ordinal that defines chunk membership. Duplicates are partitioned by CIK
#: *value*, not by text: ``1985`` and ``0000001985`` are one registrant written two
#: ways, and padding is applied only after this point, so text comparison would let
#: both through and hand the cohort a duplicate. It is stable across thread counts
#: and memory limits, so the cohort identity does not depend on the machine that
#: compiled it.
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

#: The same pass, counted rather than written, so the cohort manifest can report
#: what the input contained instead of only what survived. One scan classifies
#: every row; repeating the reader per count would re-read the file each time.
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

#: A bare count for listing a candidate input without compiling it. Counts
#: distinct CIK *values*, not distinct texts, because ``1985`` and ``0000001985``
#: are one registrant written two ways and the cohort keeps only the first.
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

    The limit is part of the key because it selects a different cohort from the
    same file: identity is derived after truncation, so a bounded cohort and the
    full cohort over one input are two different cohorts and must not share a
    directory.
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

    The result is keyed by the source digest, so re-running against an unchanged
    input reuses the dataset instead of recompiling it. A missing input and an
    input with no usable CIKs both fail loudly: a curator who pointed at the wrong
    file should not get a plan over an empty cohort.
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

    Listing an input has to stay cheap: it is a candidate menu, not a cohort the
    caller intends to run. Nothing is written and no identity is derived.
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
