"""The full SEC registrant index as a resumable cohort.

Compiled offline from an immutable source snapshot, so planning never touches
the network; the payload is split at the sink because a name may hold colons.
"""

from __future__ import annotations

import json
from pathlib import Path

from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.duckdb import connect, copy_query_to_parquet

from .manifest import cik_cohort_key
from .paths import MetadataPaths
from .roster import Roster, RosterError, read_roster
from .source_registry import SOURCE_UNIVERSE_NAME, SourceSnapshot, load_source_snapshot

UNIVERSE_SCHEMA_VERSION = "1.0.0"
UNIVERSE_COHORT_MANIFEST_KIND = "cik_lookup_cohort"
NAME_RULE = "alphabetically first name per registrant"

__all__ = [
    "NAME_RULE",
    "UNIVERSE_COHORT_MANIFEST_KIND",
    "UNIVERSE_SCHEMA_VERSION",
    "compile_universe_cohort",
]

#: A line is usable only when it is ``name:cik:`` with a CIK in range.
_UNIVERSE_VALIDATION_QUERY = """
SELECT count(*)
FROM read_csv(?, auto_detect=false, header=false, columns={'line':'VARCHAR'},
              delim='\\x01', quote='', escape='', strict_mode=false)
WHERE NOT (
    regexp_matches(line, '^(.*):[0-9]{1,10}:$')
    AND try_cast(regexp_extract(line, ':([0-9]{1,10}):$', 1) AS BIGINT)
        BETWEEN 1 AND 9999999999
)
"""

#: One registrant, one name: the alphabetically first, in CIK order.
#: Ordinals follow CIK value, never file order.
_UNIVERSE_COHORT_QUERY = """
WITH parsed AS (
    SELECT
        regexp_extract(line, ':([0-9]{1,10}):$', 1) AS cik,
        rtrim(regexp_replace(line, ':[0-9]{1,10}:$', ''), ':') AS name,
        regexp_matches(line, '^(.*):[0-9]{1,10}:$')
            AND try_cast(regexp_extract(line, ':([0-9]{1,10}):$', 1) AS BIGINT)
                BETWEEN 1 AND 9999999999 AS valid
    FROM read_csv(?, auto_detect=false, header=false, columns={'line':'VARCHAR'},
                  delim='\\x01', quote='', escape='', strict_mode=false)
),
deduped AS (
    SELECT cik, name
    FROM parsed
    WHERE valid
    QUALIFY row_number() OVER (
        PARTITION BY try_cast(cik AS BIGINT) ORDER BY name
    ) = 1
)
SELECT ordinal, cik_padded, name
FROM (
    SELECT
        row_number() OVER (ORDER BY try_cast(cik AS BIGINT)) - 1 AS ordinal,
        printf('%010d', try_cast(cik AS BIGINT)) AS cik_padded,
        name
    FROM deduped
)
WHERE ? < 0 OR ordinal < ?
ORDER BY ordinal
"""


def _refuse_malformed(raw_path: Path) -> None:
    """Refuse a payload holding a line that is not ``name:cik:``.

    A partial index would silently shrink the universe.
    """
    con = connect()
    try:
        malformed = int(
            con.execute(_UNIVERSE_VALIDATION_QUERY, [str(raw_path)]).fetchone()[0]
        )
    finally:
        con.close()
    if malformed:
        raise RosterError(
            f"cik lookup index has {malformed} malformed line(s); "
            "a partial index would silently shrink the universe"
        )


def _reuse_cohort(
    manifest_path: Path, dataset: Path, *, source_snapshot_id: str, limit: int | None
) -> Roster | None:
    """Return a previously compiled cohort when it still matches the source."""
    if not manifest_path.is_file() or not dataset.is_file():
        return None
    try:
        recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if recorded.get("manifest_kind") != UNIVERSE_COHORT_MANIFEST_KIND:
        return None
    if recorded.get("source_snapshot_id") != source_snapshot_id:
        return None
    if recorded.get("selected_limit") != limit:
        return None
    expected = str(recorded.get("dataset_sha256", ""))
    if not expected or file_sha256(dataset) != expected:
        return None
    try:
        return read_roster(
            dataset, expected_roster_id=str(recorded.get("roster_id", ""))
        )
    except (FileNotFoundError, RosterError):
        return None


def _write_cohort_manifest(
    manifest_path: Path,
    *,
    snapshot: SourceSnapshot,
    roster: Roster,
    limit: int | None,
    dataset: Path,
) -> None:
    """Record how the cohort was compiled, so a rerun can trust it."""
    manifest = snapshot.manifest
    atomic_write_json(
        manifest_path,
        {
            "manifest_kind": UNIVERSE_COHORT_MANIFEST_KIND,
            "manifest_schema_version": UNIVERSE_SCHEMA_VERSION,
            "source": SOURCE_UNIVERSE_NAME,
            "source_snapshot_id": str(manifest["snapshot_id"]),
            "raw_sha256": str(manifest["raw_sha256"]),
            "selected_limit": limit,
            "roster_id": roster.roster_id,
            "row_count": roster.row_count,
            "dataset_sha256": file_sha256(dataset),
            "line_count": manifest.get("line_count", 0),
            "distinct_cik_count": manifest.get("distinct_cik_count", 0),
            "collapsed_name_count": manifest.get("collapsed_name_count", 0),
            "name_rule": NAME_RULE,
        },
    )


def compile_universe_cohort(
    metadata_paths: MetadataPaths,
    *,
    source_snapshot_id: str,
    limit: int | None = None,
) -> Roster:
    """Compile a published universe snapshot into a content-addressed cohort.

    Keyed by snapshot id, so an unchanged index reuses its dataset.
    """
    snapshot = load_source_snapshot(
        metadata_paths.source_manifest_file(SOURCE_UNIVERSE_NAME, source_snapshot_id)
    )
    key = cik_cohort_key(f"universe-{source_snapshot_id}", limit)
    dataset = metadata_paths.compiled_cohort_file(key)
    manifest_path = metadata_paths.compiled_cohort_manifest(key)

    reused = _reuse_cohort(
        manifest_path,
        dataset,
        source_snapshot_id=source_snapshot_id,
        limit=limit,
    )
    if reused is not None:
        return reused

    raw_path = Path(snapshot.raw_path)
    _refuse_malformed(raw_path)

    bounded = -1 if limit is None else int(limit)
    con = connect()
    try:
        copy_query_to_parquet(
            con,
            _UNIVERSE_COHORT_QUERY,
            dataset,
            params=[str(raw_path), str(bounded), str(bounded)],
        )
    finally:
        con.close()

    roster = read_roster(dataset)
    _write_cohort_manifest(
        manifest_path,
        snapshot=snapshot,
        roster=roster,
        limit=limit,
        dataset=dataset,
    )
    return roster
