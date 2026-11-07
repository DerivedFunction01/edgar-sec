"""Feed-driven refresh of a published snapshot.
The feed is a discovery trigger only: it names affected CIKs, the canonical
rows still come from the per-CIK fetch, and every other CIK carries forward.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from edgar_sec.domain.feeds.models import FilingEvent
from edgar_sec.domain.submissions.schemas import SUBMISSION_METADATA_SCHEMA
from edgar_sec.engine.feeds.client import FeedClient
from edgar_sec.foundation.hashing import sha256_text
from edgar_sec.foundation.runtime.settings.runtime import DEFAULT_CHUNK_SIZE
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
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
from .roster import Roster, write_roster_rows
from .sec_client import SubmissionsClient
from .snapshot import SnapshotCatalogError, resolve_snapshot_parts
from .validation import find_duplicate_accessions
from .worker import run_chunk_ids

__all__ = [
    "RefreshResult",
    "branch_tip",
    "refresh",
    "refresh_roster_path",
]


@dataclass(frozen=True, slots=True)
class RefreshResult:
    """Outcome of one feed refresh; ``report`` is ``None`` for a no-op."""

    base_snapshot_id: str
    new_snapshot_id: str
    base_row_count: int
    events_seen: int
    pages_pulled: int
    parse_failures: int
    new_accessions: tuple[str, ...]
    affected_ciks: tuple[str, ...]
    carried_rows: int
    normalized_rows: int
    report: MergeReport | None
    no_op: bool = False

    @property
    def total_row_count(self) -> int:
        """Rows in the newly published snapshot, or in the unchanged base."""
        return self.report.row_count if self.report is not None else self.base_row_count


def branch_tip(metadata: MetadataPaths, branch_name: str = "main") -> str:
    """Snapshot id the branch names, or a refusal when it names none."""
    try:
        catalog = DAGCatalog(metadata.snapshots_root, read_only=True)
    except FileNotFoundError as exc:
        raise SnapshotCatalogError("snapshot catalog is missing") from exc
    pointer = catalog.read_pointer(branch_name)
    if pointer is None:
        raise SnapshotCatalogError(f"branch {branch_name!r} has no published tip")
    return str(pointer["snapshot_id"])


@dataclass(frozen=True, slots=True)
class _FeedWindow:
    """One bounded feed walk: deduped events plus the walk's accounting."""

    events: tuple[FilingEvent, ...]
    events_seen: int
    pages_pulled: int
    parse_failures: int


def _walk_feed(feed_client: FeedClient, bound: datetime | None) -> _FeedWindow:
    """Pull getcurrent pages to the client's stop conditions, deduping by key.
    Only accession keys are held, so the walk's state is one feed window.
    """
    failures_before = len(feed_client.parse_failures)
    seen: dict[str, FilingEvent] = {}
    events_seen = 0
    pages = 0
    start = 0
    for _page in range(feed_client.max_pages):
        outcome = feed_client.current_filings_page(start=start)
        pages += 1
        if not outcome.events and not outcome.failures:
            break
        events_seen += len(outcome.events)
        at_or_before = 0
        for event in outcome.events:
            if (
                bound is not None
                and event.acceptance_datetime is not None
                and event.acceptance_datetime <= bound
            ):
                at_or_before += 1
                continue
            if event.accession_normalized not in seen:
                seen[event.accession_normalized] = event
        if bound is not None and at_or_before == len(outcome.events):
            break
        start += len(outcome.events) + len(outcome.failures)
    return _FeedWindow(
        events=tuple(seen.values()),
        events_seen=events_seen,
        pages_pulled=pages,
        parse_failures=len(feed_client.parse_failures) - failures_before,
    )


_MAX_ACCEPTANCE_QUERY = """
SELECT max(acceptance) FROM (
    SELECT unnest(filings).acceptance_datetime AS acceptance
    FROM read_parquet(?)
) WHERE acceptance IS NOT NULL AND acceptance <> ''
"""

_STORED_ACCESSIONS_QUERY = """
SELECT cik, acc FROM (
    SELECT cik, unnest(filings).accession_number_normalized AS acc
    FROM read_parquet(?)
) WHERE cik = ANY(?) AND acc IS NOT NULL
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


def _tip_bound(metadata: MetadataPaths, snapshot_id: str) -> datetime | None:
    """The tip's maximum stored acceptance datetime, the overlap bound."""
    parts = resolve_snapshot_parts(metadata, snapshot_id)
    con = connect()
    try:
        row = con.execute(
            _MAX_ACCEPTANCE_QUERY, [[str(path) for path in parts.paths]]
        ).fetchone()
    finally:
        con.close()
    if not row or not row[0]:
        return None
    parsed = datetime.fromisoformat(str(row[0]))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _stored_accessions(
    metadata: MetadataPaths, snapshot_id: str, candidates: list[str]
) -> dict[str, set[str]]:
    """Stored accession keys for candidate CIKs only, read store-side."""
    if not candidates:
        return {}
    parts = resolve_snapshot_parts(metadata, snapshot_id)
    con = connect()
    try:
        rows = con.execute(
            _STORED_ACCESSIONS_QUERY,
            [[str(path) for path in parts.paths], candidates],
        ).fetchall()
    finally:
        con.close()
    stored: dict[str, set[str]] = {}
    for cik, accession in rows:
        stored.setdefault(str(cik), set()).add(str(accession))
    return stored


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


def refresh_roster_path(
    metadata: MetadataPaths, base_snapshot_id: str, affected: list[str]
) -> Path:
    """Transient destination for a base-and-window-specific refresh roster."""
    key = sha256_text(f"refresh:{base_snapshot_id}:{','.join(affected)}")
    return metadata.transient_dir(f"refresh-{key}") / "ciks.parquet"


def _refresh_roster(
    metadata: MetadataPaths,
    base_snapshot_id: str,
    affected: list[str],
    names: dict[str, str],
) -> Roster:
    """Write the roster covering exactly the affected CIKs, in CIK order."""
    rows = [(cik, names.get(cik, "")) for cik in affected]
    roster, _digest = write_roster_rows(
        rows, refresh_roster_path(metadata, base_snapshot_id, affected)
    )
    return roster


def refresh(
    client: SubmissionsClient,
    feed_client: FeedClient,
    metadata_paths: MetadataPaths,
    *,
    base_snapshot_id: str = "",
    new_snapshot_id: str = "",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    workers: int | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
    branch_name: str = "main",
    expected_branch_tip: str | None = None,
) -> RefreshResult:
    """Refresh the branch tip's stale CIKs from the current-filings feed.
    A matching window publishes nothing; carried rows stage store-side.
    """
    emit = _safe_progress(progress)
    base_id = base_snapshot_id or branch_tip(metadata_paths, branch_name)
    base_parts = resolve_snapshot_parts(metadata_paths, base_id)
    base_rows = base_parts.row_count

    window = _walk_feed(feed_client, _tip_bound(metadata_paths, base_id))
    feed_by_cik: dict[str, set[str]] = {}
    names: dict[str, str] = {}
    for event in window.events:
        cik = event.cik.to_10digit()
        feed_by_cik.setdefault(cik, set()).add(event.accession_normalized)
        names.setdefault(cik, event.company_name)
    candidates = sorted(feed_by_cik)
    stored = _stored_accessions(metadata_paths, base_id, candidates)
    new_accessions = tuple(
        sorted(
            accession
            for cik in candidates
            for accession in feed_by_cik[cik] - stored.get(cik, set())
        )
    )
    affected = [cik for cik in candidates if feed_by_cik[cik] - stored.get(cik, set())]
    if not affected:
        return RefreshResult(
            base_snapshot_id=base_id,
            new_snapshot_id="",
            base_row_count=base_rows,
            events_seen=window.events_seen,
            pages_pulled=window.pages_pulled,
            parse_failures=window.parse_failures,
            new_accessions=(),
            affected_ciks=(),
            carried_rows=base_rows,
            normalized_rows=0,
            report=None,
            no_op=True,
        )

    members = _base_members(metadata_paths, base_id, affected)
    carried_expected = base_rows - len(members)
    roster = _refresh_roster(metadata_paths, base_id, affected, names)
    fingerprint = sha256_text(
        f"feed-refresh:{base_id}:{','.join(sorted(new_accessions))}"
    )
    plan = build_plan(
        roster,
        chunk_size=chunk_size,
        kind="refresh",
        parent_id=base_id,
        input_name="feed:current_filings",
        input_fingerprint=fingerprint,
    )
    resolved_snapshot_id = new_snapshot_id or plan.plan_id
    run_paths = resolve_run_paths(plan.plan_id, metadata_paths.artifacts_root)
    write_plan(plan, run_paths)
    emit({"type": "refresh_plan", "plan_id": plan.plan_id, "row_count": plan.row_count})
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
                f"refresh rejected: carried {carried_rows} rows "
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
        kind="refresh",
        parent_snapshot_id=base_id,
        roster_id=plan.roster.roster_id,
        delta_roster_id=plan.roster.roster_id,
    )
    con = connect()
    try:
        emit({"type": "merge_stage", "stage": "validating"})
        if find_null_keys(con, inputs, "cik"):
            raise MergeError("refresh rejected: null CIK in merged inputs")
        duplicates = find_duplicate_keys(con, inputs, "cik")
        if duplicates:
            raise MergeError(
                f"refresh rejected: CIKs appear in both carried and fresh: {duplicates}"
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
            f"refresh rejected: published row count {row_count} "
            f"!= expected {expected_rows} "
            f"({carried_expected} carried + {plan.row_count} fresh)"
        )
    report.row_count = row_count
    report.parts_digest = ordered_parts_fingerprint(
        [str(part["sha256"]) for part in report.parts]
    )
    stray = _ciks_outside_expected(
        metadata_paths, base_id, plan.roster, [str(path) for path in part_paths]
    )
    if stray:
        raise MergeError(
            "refresh rejected: merged CIK set differs from base plus "
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
    return RefreshResult(
        base_snapshot_id=base_id,
        new_snapshot_id=resolved_snapshot_id,
        base_row_count=base_rows,
        events_seen=window.events_seen,
        pages_pulled=window.pages_pulled,
        parse_failures=window.parse_failures,
        new_accessions=new_accessions,
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
        raise MergeError("cannot verify a refresh against an empty roster")
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
