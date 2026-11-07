"""Local submissions snapshot reads for the fast path.

Builds the same ``FilingAggregate`` rows as the live submissions fetch from
the latest published submissions snapshot, so covered CIKs need no HTTP call.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from edgar_sec.apps.client.cache import DocumentCache
from edgar_sec.apps.client.fast_query.submissions import materialize_from_payload
from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.domain.identity import Cik
from edgar_sec.domain.sec_urls import SURFACE_SUBMISSIONS
from edgar_sec.foundation.runtime.paths import snapshots_root
from edgar_sec.foundation.runtime.settings import resolve_surface_ttl_s
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.traversal import walk_lineage
from edgar_sec.infra.storage.duckdb import connect, sql_literal

__all__ = ["materialize_from_snapshot"]

_METADATA_DATASET = "metadata"
_RELATION = "submissions"
_INDEX_RELATION = "cik_index"


def _fresh_after() -> datetime | None:
    """Oldest snapshot-node creation time the submissions policy still serves.

    Freshness is the policy's question, not the caller's: a node older than
    the submissions surface window is skipped, so its CIKs fall to live fetch.
    """
    ttl_s = resolve_surface_ttl_s(SURFACE_SUBMISSIONS)
    if ttl_s is None:
        return None
    return datetime.now(UTC) - timedelta(seconds=ttl_s)


def _node_is_fresh(node: Any, fresh_after: datetime | None) -> bool:
    if fresh_after is None:
        return True
    try:
        created = datetime.fromisoformat(str(node.created_at))
    except ValueError:
        return False
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return created >= fresh_after


def materialize_from_snapshot(
    ciks: Sequence[Any],
    forms: str | Sequence[str] | None,
    dates: str | None,
    limit: int | None,
    factories: dict[str, Any],
    doc_cache: DocumentCache,
    *,
    artifacts_root: Path | str,
) -> dict[str, list[FilingAggregate]]:
    """Return aggregates keyed by CIK for every CIK the snapshot covers.

    Absent CIKs are absent from the map (the caller's live-fetch signal), and
    any snapshot problem yields an empty map rather than an error.
    """
    wanted: dict[str, Any] = {}
    for cik in ciks or ():
        try:
            key = (cik if isinstance(cik, Cik) else Cik.from_raw(cik)).to_10digit()
        except Exception:
            continue
        wanted[key] = cik
    if not wanted:
        return {}
    try:
        return _read_snapshot_rows(
            wanted, forms, dates, limit, factories, doc_cache, artifacts_root
        )
    except Exception:
        return {}


def _read_snapshot_rows(
    wanted: dict[str, Any],
    forms: str | Sequence[str] | None,
    dates: str | None,
    limit: int | None,
    factories: dict[str, Any],
    doc_cache: DocumentCache,
    artifacts_root: Path | str,
) -> dict[str, list[FilingAggregate]]:
    root = snapshots_root(artifacts_root, _METADATA_DATASET)
    catalog = DAGCatalog(root, read_only=True)
    pointer = catalog.read_pointer("main")
    if pointer is None:
        return {}
    chain = walk_lineage(root, str(pointer["snapshot_id"]), read_only=True)
    fresh_after = _fresh_after()
    covered: dict[str, list[FilingAggregate]] = {}
    remaining = dict(wanted)
    for node in reversed(chain.nodes):
        if not remaining:
            break
        if _RELATION not in node.relations:
            continue
        if not _node_is_fresh(node, fresh_after):
            continue
        part_paths = catalog.resolve_relation(
            node.snapshot_id,
            _RELATION,
            relative_to=root / node.snapshot_id,
            verify_digests=False,
        )
        if not part_paths:
            continue
        index_paths: tuple[Path, ...] = ()
        if _INDEX_RELATION in node.relations:
            index_paths = catalog.resolve_relation(
                node.snapshot_id,
                _INDEX_RELATION,
                relative_to=root / node.snapshot_id,
                verify_digests=False,
            )
        payloads = _query_parts(
            part_paths,
            sorted(remaining),
            index_paths=index_paths,
            part_row_counts=tuple(
                descriptor.row_count for descriptor in node.relations[_RELATION]
            ),
        )
        for cik_key, payload in payloads.items():
            covered[cik_key] = materialize_from_payload(
                remaining[cik_key],
                payload,
                forms,
                dates,
                limit,
                factories,
                doc_cache,
            )
            remaining.pop(cik_key, None)
    return covered


def _locate_in_index(
    index_paths: tuple[Path, ...], cik_list: str
) -> tuple[dict[str, int], int] | None:
    """Return wanted CIKs' zero-based index positions and the index size.

    The index is the node's sorted distinct CIK list, so a position plus
    the parts' row counts identifies the part holding each CIK.
    """
    paths = [str(path) for path in index_paths]
    try:
        with connect() as con:
            rows = con.execute(
                f"""
                SELECT cik, rn - 1, total
                FROM (
                    SELECT cik,
                           row_number() OVER (ORDER BY cik) AS rn,
                           count(*) OVER () AS total
                    FROM read_parquet(?)
                )
                WHERE cik IN ({cik_list})
                """,
                [paths],
            ).fetchall()
    except Exception:
        return None
    if not rows:
        return {}, 0
    totals = {int(row[2]) for row in rows}
    if len(totals) != 1:
        return None
    return {str(row[0]): int(row[1]) for row in rows}, totals.pop()


def _resolve_target_parts(
    part_paths: tuple[Path, ...],
    part_row_counts: tuple[int, ...],
    positions: dict[str, int],
    index_size: int,
) -> tuple[Path, ...] | None:
    """Map index positions to the parts holding them, or None on drift.

    Descriptor order and row counts must partition the sorted index
    exactly; any mismatch refuses targeting rather than guessing a part.
    """
    if len(part_row_counts) != len(part_paths):
        return None
    if sum(part_row_counts) != index_size or any(
        count <= 0 for count in part_row_counts
    ):
        return None
    starts: list[int] = []
    offset = 0
    for count in part_row_counts:
        starts.append(offset)
        offset += count
    chosen: set[int] = set()
    for position in positions.values():
        if not 0 <= position < index_size:
            return None
        chosen.add(bisect_right(starts, position) - 1)
    return tuple(part_paths[i] for i in sorted(chosen))


def _query_parts(
    part_paths: tuple[Path, ...],
    cik_keys: list[str],
    *,
    index_paths: tuple[Path, ...] = (),
    part_row_counts: tuple[int, ...] = (),
) -> dict[str, dict[str, Any]]:
    cik_list = ", ".join(sql_literal(cik) for cik in cik_keys)
    targets = part_paths
    present: set[str] | None = None
    if index_paths:
        located = _locate_in_index(index_paths, cik_list)
        if located is not None:
            positions, index_size = located
            present = set(positions)
            if not present:
                return {}
            resolved = _resolve_target_parts(
                part_paths, part_row_counts, positions, index_size
            )
            if resolved is not None:
                targets = resolved
    paths = [str(path) for path in targets]
    with connect() as con:
        if present is None:
            present = {
                str(row[0])
                for row in con.execute(
                    f"SELECT DISTINCT cik FROM read_parquet(?) WHERE cik IN ({cik_list})",
                    [paths],
                ).fetchall()
            }
            if not present:
                return {}
        filing_rows = con.execute(
            f"""
            SELECT cik,
                   f.accession_number, f.filing_date, f.report_date, f.form,
                   f.primary_document
            FROM (
                SELECT cik, unnest(filings) AS f
                FROM read_parquet(?)
                WHERE cik IN ({cik_list})
            )
            """,
            [paths],
        ).fetchall()
    arrays: dict[str, dict[str, list[Any]]] = {
        cik: {
            "accessionNumber": [],
            "filingDate": [],
            "reportDate": [],
            "form": [],
            "primaryDocument": [],
        }
        for cik in present
    }
    for row in filing_rows:
        bucket = arrays[str(row[0])]
        bucket["accessionNumber"].append(row[1])
        bucket["filingDate"].append(row[2])
        bucket["reportDate"].append(row[3])
        bucket["form"].append(row[4])
        bucket["primaryDocument"].append(row[5])
    return {cik: {"filings": {"recent": bucket}} for cik, bucket in arrays.items()}
