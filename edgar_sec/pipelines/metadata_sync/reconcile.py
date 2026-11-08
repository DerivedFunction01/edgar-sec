"""Daily-index reconciliation of a published snapshot.

The index is a discovery trigger only: it names accessions the tip lacks,
the canonical rows still come from the per-CIK fetch, and every other CIK
carries forward. The diff is a store-side anti-join, never Python sets.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from edgar_sec.domain.index_urls import daily_index_url
from edgar_sec.domain.submissions.schemas import SUBMISSION_METADATA_SCHEMA
from edgar_sec.engine.index_pages.parser_idx import (
    IndexRow,
    MalformedIndexRow,
    parse_index_bytes,
)
from edgar_sec.foundation.hashing import sha256_text
from edgar_sec.foundation.runtime.settings.runtime import (
    DEFAULT_CHUNK_SIZE,
    resolve_read_batch_size,
)
from edgar_sec.infra.sec_http.errors import PermanentHttpError
from edgar_sec.infra.storage.dag.manifest import ordered_parts_fingerprint
from edgar_sec.infra.storage.duckdb import (
    connect,
    copy_query_to_parquet,
    find_duplicate_keys,
    find_null_keys,
)

from .augmentation import base_cik_sources
from .merger import (
    MergeError,
    MergeReport,
    _safe_progress,
    publish_cik_index,
    publish_parts,
    publish_snapshot,
)
from .paths import MetadataPaths, resolve_run_paths
from .planner import build_plan, utc_now_iso, write_plan
from .refresh import branch_tip
from .roster import Roster, write_roster_rows
from .sec_client import SubmissionsClient
from .snapshot import resolve_snapshot_parts
from .validation import find_duplicate_accessions
from .worker import run_chunk_ids

__all__ = ["ReconcileResult", "reconcile", "reconcile_roster_path"]


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    """Outcome of one index reconciliation; ``report`` is ``None`` for a no-op."""

    base_snapshot_id: str
    new_snapshot_id: str
    base_row_count: int
    days_pulled: int
    days_missing: int
    index_rows: int
    malformed_rows: int
    missing_accessions: tuple[str, ...]
    affected_ciks: tuple[str, ...]
    carried_rows: int
    normalized_rows: int
    report: MergeReport | None
    no_op: bool = False

    @property
    def total_row_count(self) -> int:
        """Rows in the newly published snapshot, or in the unchanged base."""
        return self.report.row_count if self.report is not None else self.base_row_count


_MISSING_QUERY = """
WITH tip AS (
    SELECT unnest(filings).accession_number_normalized AS acc
    FROM read_parquet(?)
)
SELECT i.accession, i.cik
FROM (SELECT DISTINCT accession, cik FROM idx_rows) AS i
LEFT JOIN tip ON tip.acc = i.accession
WHERE tip.acc IS NULL
ORDER BY i.cik, i.accession
"""

_NAMES_QUERY = """
SELECT cik, min(company_name) FROM idx_rows WHERE cik = ANY(?) GROUP BY cik
"""

_MEMBER_QUERY = """
SELECT DISTINCT cik FROM read_parquet(?) WHERE cik = ANY(?)
"""

_CARRIED_QUERY = """
SELECT base.* FROM read_parquet(?) AS base
LEFT JOIN read_parquet(?) AS affected ON base.cik = affected.cik_padded
WHERE affected.cik_padded IS NULL
"""

_SET_DIFFERENCE_QUERY = """
WITH merged AS (SELECT DISTINCT cik FROM read_parquet(?)),
     base AS (SELECT DISTINCT cik FROM read_parquet(?)),
     fetched AS (SELECT DISTINCT cik_padded AS cik FROM read_parquet(?)),
     expected AS (SELECT cik FROM base UNION SELECT cik FROM fetched)
SELECT
    (SELECT count(*) FROM (SELECT cik FROM merged EXCEPT SELECT cik FROM expected))
    + (SELECT count(*) FROM (SELECT cik FROM expected EXCEPT SELECT cik FROM merged))
"""


def _path_list(paths: list[str]) -> list[str] | str:
    """Bind a single source directly and several as a list."""
    return paths[0] if len(paths) == 1 else paths


@dataclass(frozen=True, slots=True)
class _StagedIndex:
    """Accounting for one staged date range of daily-index rows."""

    days_pulled: int
    days_missing: int
    rows: int
    malformed: int


def _stage_index(
    con: Any,
    fetch_bytes: Callable[[str], bytes],
    start: date,
    end: date,
) -> _StagedIndex:
    """Stream each day's master index into the staging table in batches."""
    con.execute(
        "CREATE TABLE idx_rows (accession VARCHAR, cik VARCHAR, company_name VARCHAR)"
    )
    batch_size = resolve_read_batch_size()
    batch: list[tuple[str, str, str]] = []
    days_pulled = 0
    days_missing = 0
    rows = 0
    malformed = 0

    def flush() -> None:
        if batch:
            con.executemany("INSERT INTO idx_rows VALUES (?, ?, ?)", batch)
            batch.clear()

    day = start
    while day <= end:
        try:
            payload = fetch_bytes(daily_index_url(day))
        except PermanentHttpError:
            days_missing += 1
            day += timedelta(days=1)
            continue
        days_pulled += 1
        for outcome in parse_index_bytes(payload, "master"):
            if isinstance(outcome, MalformedIndexRow) or outcome.accession is None:
                malformed += 1
                continue
            assert isinstance(outcome, IndexRow)
            batch.append((outcome.accession, outcome.cik_padded, outcome.company_name))
            rows += 1
            if len(batch) >= batch_size:
                flush()
        day += timedelta(days=1)
    flush()
    return _StagedIndex(days_pulled, days_missing, rows, malformed)


def reconcile_roster_path(
    metadata: MetadataPaths, base_snapshot_id: str, affected: list[str]
) -> Path:
    """Transient destination for a base-and-range-specific reconcile roster."""
    key = sha256_text(f"reconcile:{base_snapshot_id}:{','.join(affected)}")
    return metadata.transient_dir(f"reconcile-{key}") / "ciks.parquet"


def _base_members(
    metadata: MetadataPaths, snapshot_id: str, candidates: list[str]
) -> set[str]:
    """Which candidate CIKs the base snapshot already holds a row for."""
    if not candidates:
        return set()
    sources, _from_parts = base_cik_sources(metadata, snapshot_id)
    con = connect()
    try:
        rows = con.execute(_MEMBER_QUERY, [_path_list(sources), candidates]).fetchall()
    finally:
        con.close()
    return {str(row[0]) for row in rows}


def reconcile(
    client: SubmissionsClient,
    metadata_paths: MetadataPaths,
    *,
    start_date: date,
    end_date: date,
    fetch_bytes: Callable[[str], bytes] | None = None,
    new_snapshot_id: str = "",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    workers: int | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
    branch_name: str = "main",
    expected_branch_tip: str | None = None,
) -> ReconcileResult:
    """Publish the accessions the daily index proves and the tip lacks.

    A zero-diff range publishes nothing; carried rows stage store-side.
    """
    if end_date < start_date:
        raise ValueError("end_date must not precede start_date")
    emit = _safe_progress(progress)
    fetch = fetch_bytes or client.http.get_bytes
    base_id = branch_tip(metadata_paths, branch_name)
    base_parts = resolve_snapshot_parts(metadata_paths, base_id)
    base_rows = base_parts.row_count

    con = connect()
    try:
        staged = _stage_index(con, fetch, start_date, end_date)
        missing = con.execute(
            _MISSING_QUERY, [[str(path) for path in base_parts.paths]]
        ).fetchall()
        missing_accessions = tuple(sorted(str(row[0]) for row in missing))
        affected = sorted({str(row[1]) for row in missing})
        names = (
            {
                str(cik): str(name)
                for cik, name in con.execute(_NAMES_QUERY, [affected]).fetchall()
            }
            if affected
            else {}
        )
    finally:
        con.close()

    if not affected:
        return ReconcileResult(
            base_snapshot_id=base_id,
            new_snapshot_id="",
            base_row_count=base_rows,
            days_pulled=staged.days_pulled,
            days_missing=staged.days_missing,
            index_rows=staged.rows,
            malformed_rows=staged.malformed,
            missing_accessions=(),
            affected_ciks=(),
            carried_rows=base_rows,
            normalized_rows=0,
            report=None,
            no_op=True,
        )

    members = _base_members(metadata_paths, base_id, affected)
    carried_expected = base_rows - len(members)
    roster_rows = [(cik, names.get(cik, "")) for cik in affected]
    roster, _digest = write_roster_rows(
        roster_rows,
        reconcile_roster_path(metadata_paths, base_id, affected),
    )
    fingerprint = sha256_text(
        f"daily-reconcile:{base_id}:{','.join(missing_accessions)}"
    )
    plan = build_plan(
        roster,
        chunk_size=chunk_size,
        kind="reconcile",
        parent_id=base_id,
        input_name="index:daily_index",
        input_fingerprint=fingerprint,
    )
    resolved_snapshot_id = new_snapshot_id or plan.plan_id
    run_paths = resolve_run_paths(plan.plan_id, metadata_paths.artifacts_root)
    write_plan(plan, run_paths)
    emit(
        {"type": "reconcile_plan", "plan_id": plan.plan_id, "row_count": plan.row_count}
    )
    run_chunk_ids(
        client,
        plan,
        run_paths,
        plan.chunk_ids(),
        snapshot_id=resolved_snapshot_id,
        workers=workers,
        progress=emit,
    )
    fresh_paths = [run_paths.chunk_file(chunk_id) for chunk_id in plan.chunk_ids()]

    carried_path = metadata_paths.transient_dir(plan.plan_id) / "carried.parquet"
    carried_rows = 0
    if carried_expected:
        con = connect()
        try:
            carried_rows = copy_query_to_parquet(
                con,
                _CARRIED_QUERY,
                carried_path,
                params=[
                    [str(path) for path in base_parts.paths],
                    str(plan.roster.dataset),
                ],
                schema=SUBMISSION_METADATA_SCHEMA,
            )
        finally:
            con.close()
        if carried_rows != carried_expected:
            raise MergeError(
                f"reconcile rejected: carried {carried_rows} rows "
                f"!= expected {carried_expected}"
            )

    inputs = ([str(carried_path)] if carried_rows else []) + [
        str(path) for path in fresh_paths
    ]
    report = MergeReport(
        snapshot_id=resolved_snapshot_id,
        chunk_count=plan.chunk_count,
        plan_id=plan.plan_id,
        input_fingerprint=plan.input_fingerprint,
        kind="reconcile",
        parent_snapshot_id=base_id,
        roster_id=plan.roster.roster_id,
        delta_roster_id=plan.roster.roster_id,
    )
    con = connect()
    try:
        emit({"type": "merge_stage", "stage": "validating"})
        if find_null_keys(con, inputs, "cik"):
            raise MergeError("reconcile rejected: null CIK in merged inputs")
        duplicates = find_duplicate_keys(con, inputs, "cik")
        if duplicates:
            raise MergeError(
                f"reconcile rejected: CIKs appear in both carried and fresh: "
                f"{duplicates}"
            )
        report.duplicate_accessions = find_duplicate_accessions(con, inputs)
        if report.duplicate_accessions:
            report.warnings.append(
                f"{len(report.duplicate_accessions)} duplicate accession(s) "
                "observed; accession is not globally unique"
            )
    finally:
        con.close()

    sources: list[tuple[str, Path]] = []
    if carried_rows:
        sources.append(("chunk:carried", carried_path))
    sources.extend((f"chunk:{path.stem}", path) for path in fresh_paths)
    emit({"type": "merge_stage", "stage": "publishing_parts"})
    part_paths = publish_parts(report, metadata_paths, sources)
    row_count = sum(int(part["row_count"]) for part in report.parts)
    expected_rows = carried_expected + plan.row_count
    if row_count != expected_rows:
        raise MergeError(
            f"reconcile rejected: published row count {row_count} "
            f"!= expected {expected_rows} "
            f"({carried_expected} carried + {plan.row_count} fresh)"
        )
    report.row_count = row_count
    report.parts_digest = ordered_parts_fingerprint(
        [str(part["sha256"]) for part in report.parts]
    )
    stray = _ciks_outside_expected(
        metadata_paths, base_id, roster, [str(path) for path in part_paths]
    )
    if stray:
        raise MergeError(
            "reconcile rejected: merged CIK set differs from base plus "
            f"affected by {stray} CIKs"
        )
    publish_cik_index(report, metadata_paths, part_paths)
    report.merged_at = utc_now_iso()
    publish_snapshot(
        report,
        metadata_paths,
        branch_name=branch_name,
        expected_branch_tip=(
            expected_branch_tip if expected_branch_tip is not None else base_id
        ),
    )
    emit({"type": "readback_done", "rows": row_count})
    return ReconcileResult(
        base_snapshot_id=base_id,
        new_snapshot_id=resolved_snapshot_id,
        base_row_count=base_rows,
        days_pulled=staged.days_pulled,
        days_missing=staged.days_missing,
        index_rows=staged.rows,
        malformed_rows=staged.malformed,
        missing_accessions=missing_accessions,
        affected_ciks=tuple(affected),
        carried_rows=carried_rows,
        normalized_rows=plan.row_count,
        report=report,
        no_op=False,
    )


def _ciks_outside_expected(
    metadata_paths: MetadataPaths,
    base_snapshot_id: str,
    roster: Roster,
    published_parts: list[str],
) -> int:
    """Count the CIKs by which a merged snapshot differs from base plus roster."""
    if roster.dataset is None:
        raise MergeError("cannot verify a reconcile against an empty roster")
    sources, _from_parts = base_cik_sources(metadata_paths, base_snapshot_id)
    con = connect()
    try:
        return int(
            con.execute(
                _SET_DIFFERENCE_QUERY,
                [published_parts, _path_list(sources), str(roster.dataset)],
            ).fetchone()[0]
        )
    finally:
        con.close()
