"""Ledger publication and reads over the feeds DAG store.

The ledger is a discovery record only: publishing touches the feeds store
alone, and dedupe is a store-side anti-join against the published tip.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import pyarrow as pa

from edgar_sec.domain.feeds.models import FilingEvent
from edgar_sec.foundation.hashing import file_sha256, sha256_text
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.infra.storage.dag.anti_join import filter_candidate_delta
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.manifest import (
    DAGNodeManifest,
    ParentRef,
    PartDescriptor,
    ordered_parts_fingerprint,
)
from edgar_sec.infra.storage.dag.publication import publish_node, read_pointer
from edgar_sec.infra.storage.duckdb import connect, sql_path_list
from edgar_sec.infra.storage.parquet import (
    read_parquet_key_bounds,
    write_parquet_table,
)

from .paths import FEED_EVENTS_FILE, FeedsPaths
from .specs import FEED_EVENTS_SCHEMA, FEED_EVENTS_SCHEMA_VERSION, FEED_EVENTS_SPEC

_CANDIDATE_TABLE = "candidate_feed_events"
_ACTIVE_VIEW = "active_feed_events"


@dataclass(frozen=True, slots=True)
class PublishResult:
    """Outcome of one ledger publish attempt against the branch tip."""

    published: bool
    snapshot_id: str | None
    tip_before: str | None
    new_rows: int
    total_rows: int
    per_source_new: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SourceStats:
    """Published row count and latest fetch time for one ledger source."""

    source: str
    row_count: int
    latest_fetched_at: str | None


@dataclass(frozen=True, slots=True)
class LedgerStats:
    """Tip identity and per-source counts over the active ledger."""

    tip_snapshot_id: str
    total_rows: int
    distinct_accessions: int
    per_source: tuple[SourceStats, ...]


def ledger_tip(paths: FeedsPaths, branch: str = "main") -> str | None:
    """The branch tip snapshot id, or ``None`` when no ledger is published."""
    if not paths.catalog_file.is_file():
        return None
    pointer = read_pointer(paths.snapshots_root, branch)
    return str(pointer["snapshot_id"]) if pointer else None


def active_part_paths(paths: FeedsPaths, tip_snapshot_id: str) -> tuple[Path, ...]:
    """Active feed-events parts of the tip lineage, ancestor to tip."""
    catalog = DAGCatalog(paths.snapshots_root, read_only=True)
    return catalog.resolve_active_relation(
        tip_snapshot_id, FEED_EVENTS_SPEC.name, relative_to=paths.snapshots_root
    )


def event_rows(
    events: Iterable[FilingEvent],
    *,
    snapshot_id: str,
    fetched_at: datetime,
) -> list[dict[str, Any]]:
    """Expand events into one ledger row per accession and source."""
    rows: list[dict[str, Any]] = []
    for event in events:
        for source in event.sources:
            rows.append(
                {
                    "accession": event.accession.value,
                    "accession_normalized": event.accession_normalized,
                    "source": source,
                    "cik": event.cik.to_10digit(),
                    "form": event.form,
                    "company_name": event.company_name,
                    "filing_date": event.filing_date,
                    "acceptance_datetime": (
                        event.acceptance_datetime.isoformat()
                        if event.acceptance_datetime is not None
                        else None
                    ),
                    "link": event.link,
                    "snapshot_id": snapshot_id,
                    "fetched_at": fetched_at.isoformat(),
                }
            )
    return rows


def derive_snapshot_id(
    events: Iterable[FilingEvent], *, parent_id: str | None, command: str
) -> str:
    """Content identity for a publish: parent, command, and served keys."""
    keys = sorted(
        {
            (event.accession_normalized, source)
            for event in events
            for source in event.sources
        }
    )
    fingerprint = sha256_text(
        canonical_json({"parent": parent_id or "", "command": command, "keys": keys})
    )
    return f"feeds-{fingerprint[:24]}"


def publish_events(
    paths: FeedsPaths,
    events: Sequence[FilingEvent],
    *,
    command: str,
    fetched_at: datetime,
    branch: str = "main",
) -> PublishResult:
    """Publish one batch of events as the next ledger snapshot.

    A DuckDB anti-join against the tip's active parts removes rows already
    published under the same accession and source; no new rows, no publish.
    """
    tip = ledger_tip(paths, branch)
    snapshot_id = derive_snapshot_id(events, parent_id=tip, command=command)
    rows = event_rows(events, snapshot_id=snapshot_id, fetched_at=fetched_at)
    staging = paths.transient_dir(snapshot_id)
    staging.mkdir(parents=True, exist_ok=True)
    candidate_file = staging / "candidate.parquet"
    write_parquet_table(
        pa.Table.from_pylist(rows, schema=FEED_EVENTS_SCHEMA), candidate_file
    )

    con = connect()
    try:
        con.execute(
            "CREATE TEMP TABLE candidate_feed_events AS "
            f"SELECT * FROM read_parquet({sql_path_list([str(candidate_file)])})"
        )
        total_before = _stage_active_view(con, paths, tip)
        filtered = filter_candidate_delta(
            con,
            (FEED_EVENTS_SPEC,),
            {FEED_EVENTS_SPEC.name: _CANDIDATE_TABLE},
            {FEED_EVENTS_SPEC.name: _ACTIVE_VIEW},
            staging / "filtered",
        )
        if filtered.is_noop:
            return PublishResult(
                published=False,
                snapshot_id=None,
                tip_before=tip,
                new_rows=0,
                total_rows=total_before,
            )
        new_rows = filtered.row_counts[FEED_EVENTS_SPEC.name]
        per_source = _per_source_counts(con, staging / "filtered")
    finally:
        con.close()

    staged_dir = staging / "snapshot"
    staged_dir.mkdir(parents=True, exist_ok=True)
    part_file = staged_dir / FEED_EVENTS_FILE
    shutil.copyfile(filtered.filtered_parts[FEED_EVENTS_SPEC.name], part_file)
    key_min, key_max = read_parquet_key_bounds(part_file, "accession_normalized")
    descriptor = PartDescriptor(
        path=f"{snapshot_id}/{FEED_EVENTS_FILE}",
        sha256=file_sha256(part_file),
        row_count=new_rows,
        byte_size=part_file.stat().st_size,
        key_min=key_min,
        key_max=key_max,
    )
    manifest = _manifest(paths, snapshot_id, tip, descriptor, command, fetched_at)
    publish_node(
        paths.snapshots_root,
        manifest,
        staged_dir=staged_dir,
        expected_parent_id=tip,
        branch_name=branch,
    )
    return PublishResult(
        published=True,
        snapshot_id=snapshot_id,
        tip_before=tip,
        new_rows=new_rows,
        total_rows=total_before + new_rows,
        per_source_new=per_source,
    )


def ledger_stats(paths: FeedsPaths, branch: str = "main") -> LedgerStats | None:
    """Per-source counts over the active ledger, or ``None`` when absent."""
    tip = ledger_tip(paths, branch)
    if tip is None:
        return None
    parts = active_part_paths(paths, tip)
    con = connect()
    try:
        view = f"SELECT * FROM read_parquet({sql_path_list([str(p) for p in parts])})"
        total, distinct = con.execute(
            f"SELECT count(*), count(DISTINCT accession_normalized) FROM ({view})"
        ).fetchone()
        rows = con.execute(
            "SELECT source, count(*), max(fetched_at) FROM "
            f"({view}) GROUP BY source ORDER BY source"
        ).fetchall()
    finally:
        con.close()
    return LedgerStats(
        tip_snapshot_id=tip,
        total_rows=int(total),
        distinct_accessions=int(distinct),
        per_source=tuple(
            SourceStats(
                source=str(r[0]),
                row_count=int(r[1]),
                latest_fetched_at=str(r[2]) if r[2] is not None else None,
            )
            for r in rows
        ),
    )


def _stage_active_view(con: Any, paths: FeedsPaths, tip: str | None) -> int:
    """Materialize the tip's active ledger as a view; return its row count."""
    if tip is None:
        con.execute(
            "CREATE TEMP VIEW active_feed_events AS "
            "SELECT * FROM candidate_feed_events WHERE false"
        )
        return 0
    parts = active_part_paths(paths, tip)
    con.execute(
        "CREATE TEMP VIEW active_feed_events AS "
        f"SELECT * FROM read_parquet({sql_path_list([str(p) for p in parts])})"
    )
    return int(con.execute("SELECT count(*) FROM active_feed_events").fetchone()[0])


def _per_source_counts(con: Any, filtered_dir: Path) -> dict[str, int]:
    part = filtered_dir / f"{FEED_EVENTS_SPEC.name}.parquet"
    rows = con.execute(
        "SELECT source, count(*) FROM "
        f"read_parquet({sql_path_list([str(part)])}) GROUP BY source"
    ).fetchall()
    return {str(source): int(count) for source, count in rows}


def _manifest(
    paths: FeedsPaths,
    snapshot_id: str,
    tip: str | None,
    descriptor: PartDescriptor,
    command: str,
    fetched_at: datetime,
) -> DAGNodeManifest:
    parents: tuple[ParentRef, ...] = ()
    anchor = snapshot_id
    depth = 0
    if tip is not None:
        catalog = DAGCatalog(paths.snapshots_root, read_only=True)
        parent = catalog.get_manifest(tip)
        parents = (
            ParentRef(
                snapshot_id=tip,
                manifest_sha256=catalog.get_manifest_sha256(tip) or "",
            ),
        )
        if parent is not None:
            anchor = parent.checkpoint_anchor_id or tip
            depth = parent.lineage_depth + 1
    return DAGNodeManifest(
        snapshot_id=snapshot_id,
        kind="delta" if tip is not None else "checkpoint",
        parents=parents,
        checkpoint_anchor_id=anchor,
        lineage_depth=depth,
        created_at=fetched_at.isoformat(),
        relations={FEED_EVENTS_SPEC.name: (descriptor,)},
        logical_fingerprint=ordered_parts_fingerprint([descriptor.sha256]),
        schema_versions={FEED_EVENTS_SPEC.name: FEED_EVENTS_SCHEMA_VERSION},
        metadata={"command": command, "fetched_at": fetched_at.isoformat()},
    )


__all__ = [
    "LedgerStats",
    "PublishResult",
    "SourceStats",
    "active_part_paths",
    "derive_snapshot_id",
    "event_rows",
    "ledger_stats",
    "ledger_tip",
    "publish_events",
]
